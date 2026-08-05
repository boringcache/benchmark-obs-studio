from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope_plan = load_script("scope_boringcache_plan.py")
verify_ccache = load_script("verify_ccache_evidence.py")
verify_xcode_log = load_script("verify_xcode_build_log.py")
render = load_script("render_comparison.py")
render_continuation = load_script("render_continuation.py")
write_result = load_script("write_phase_result.py")


class SourceSyncTest(unittest.TestCase):
    def test_advances_exactly_one_upstream_commit(self):
        current = "a" * 40
        following = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "benchmark-source.env"
            source.write_text(
                "OBS_SOURCE_REPOSITORY=obsproject/obs-studio\n"
                f"OBS_BASE_SHA={'0' * 40}\n"
                f"OBS_HEAD_SHA={current}\n"
                "OBS_VERSION_OVERRIDE=32.2.0\n"
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  'api repos/obsproject/obs-studio --jq .default_branch') echo master ;;\n"
                f"  'api repos/obsproject/obs-studio/compare/{current}...master') "
                f"echo '{{\"status\":\"ahead\",\"commits\":[{{\"sha\":\"{following}\"}}]}}' ;;\n"
                f"  'api repos/obsproject/obs-studio/commits/{following} --jq .parents[0].sha // empty') echo {current} ;;\n"
                "  *) echo \"Unexpected gh call: $*\" >&2; exit 1 ;;\n"
                "esac\n"
            )
            gh.chmod(0o755)

            subprocess.run(
                [
                    str(ROOT / "scripts/advance-source-pair.sh"),
                    str(source),
                    "OBS",
                ],
                check=True,
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            )
            settings = dict(line.split("=", 1) for line in source.read_text().splitlines())

        self.assertEqual(settings["OBS_BASE_SHA"], current)
        self.assertEqual(settings["OBS_HEAD_SHA"], following)
        self.assertEqual(settings["OBS_VERSION_OVERRIDE"], "32.2.0")


class PlanScopingTest(unittest.TestCase):
    def test_scopes_only_the_selected_adapter(self):
        source = (ROOT / ".boringcache.toml").read_text()
        result = scope_plan.scoped_plan(source, "xcode", "42", "3")
        self.assertIn('tag = "obs-studio-xcode-r42-a3"', result)
        self.assertIn('tag = "obs-studio-ccache"', result)

class CcacheEvidenceTest(unittest.TestCase):
    def test_requires_native_remote_hit_on_boringcache_rolling_build(self):
        payload = {
            "direct_cache_hit": 10,
            "cache_miss": 1,
            "remote_storage_hit": 10,
            "remote_storage_error": 0,
            "remote_storage_timeout": 0,
        }
        verify_ccache.validate(payload, "rolling", "boringcache")

        payload["remote_storage_hit"] = 0
        with self.assertRaisesRegex(ValueError, "restore remote ccache entries"):
            verify_ccache.validate(payload, "rolling", "boringcache")


class XcodeEvidenceTest(unittest.TestCase):
    def test_requires_xcode_replay_hit_diagnostic(self):
        verify_xcode_log.validate("CompileC object.o source.cpp\nremark: replayed cache hit\n")
        with self.assertRaisesRegex(ValueError, "replay hit"):
            verify_xcode_log.validate("CompileC object.o source.cpp\n")


class ComparisonTest(unittest.TestCase):
    def results(self):
        results = {}
        for surface in render.SURFACES:
            for strategy in render.STRATEGIES:
                for phase in render.PHASES:
                    seconds = 100
                    if phase == "rolling" and strategy == "boringcache":
                        seconds = 60
                    results[(surface, strategy, phase)] = {
                        "schema_version": 2,
                        "surface": surface,
                        "strategy": strategy,
                        "phase": phase,
                        "classification": write_result.classification(surface, strategy, phase),
                        "timing": {
                            "restore_seconds": 10,
                            "build_seconds": seconds,
                            "end_to_end_seconds": seconds + 10,
                        },
                        "native": None,
                    }
        return results

    def test_reports_each_surface_without_overselling(self):
        payload = render.comparison_payload(self.results())
        markdown = render.render_markdown(payload)
        self.assertEqual(payload["rolling_comparison"]["ccache"]["end_to_end_seconds_saved"], 40)
        self.assertIn("**ccache:** BoringCache saved **40s", markdown)
        self.assertIn("**xcode:** BoringCache saved **40s", markdown)

    def test_requires_all_eight_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "surface": "ccache",
                        "strategy": "actions-cache",
                        "phase": "base",
                        "classification": write_result.classification("ccache", "actions-cache", "base"),
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "missing benchmark results"):
                render.load_results(Path(directory))

    def test_ignores_raw_native_evidence_next_to_phase_results(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory)
            expected = self.results()
            for (surface, strategy, phase), payload in expected.items():
                (input_dir / f"{surface}-{strategy}-{phase}.json").write_text(
                    json.dumps(payload)
                )
            (input_dir / "ccache-actions-cache-base-native.json").write_text(
                json.dumps({"cache_miss": 560})
            )

            self.assertEqual(render.load_results(input_dir), expected)


class WorkflowContractTest(unittest.TestCase):
    def test_source_updates_run_the_compiler_cache_proof(self):
        proof = (ROOT / ".github" / "workflows" / "obs-compiler-cache-proof.yml").read_text()
        sync = (ROOT / ".github" / "workflows" / "sync.yml").read_text()

        self.assertIn('- "benchmark-source.env"', proof)
        self.assertIn('cron: "*/30 * * * *"', sync)
        self.assertIn("advance-source-pair.sh benchmark-source.env OBS", sync)
        self.assertIn("Require the previous rolling benchmark to be green", sync)
        self.assertIn("steps.previous.outputs.ready == 'true'", sync)
        self.assertIn("group: benchmark-obs-studio-compiler-cache", proof)

    def test_boringcache_workflow_uses_current_adapter_contract(self):
        source = (ROOT / ".github" / "workflows" / "obs-boringcache.yml").read_text()
        self.assertEqual(
            source.count(
                "boringcache/one@09e053620cda4d3472f26a3ddd181144a108e2c2"
            ),
            4,
        )
        self.assertEqual(source.count("cli-version: ${{ inputs.cli_version }}"), 4)
        self.assertEqual(source.count("setup: none"), 4)
        self.assertEqual(source.count("mode: ccache"), 2)
        self.assertEqual(source.count("ccache-version: 4.13.6"), 2)
        self.assertEqual(source.count("mode: xcode"), 2)
        self.assertEqual(source.count("trust-policy: publish"), 2)
        self.assertEqual(source.count("trust-policy: restore"), 2)
        self.assertEqual(source.count("working-directory: ./upstream"), 4)
        self.assertEqual(source.count("# v1.16.8"), 4)
        self.assertNotIn("BORINGCACHE_API_TOKEN", source)
        self.assertNotIn("cache-tag:", source)
        self.assertNotIn("read-only:", source)
        self.assertEqual(source.count("fail-on-cache-error: true"), 4)

    def test_result_classification_is_fail_closed(self):
        rolling = write_result.classification("ccache", "boringcache", "rolling")
        self.assertTrue(rolling["sample_valid"])
        self.assertEqual(rolling["reporting_mode"], "commit-build")
        self.assertEqual(rolling["cache_import_status"], "hit")

    def test_focused_xcode_recovery_reuses_one_immutable_cohort(self):
        proof = (ROOT / ".github" / "workflows" / "obs-compiler-cache-proof.yml").read_text()
        boringcache = (ROOT / ".github" / "workflows" / "obs-boringcache.yml").read_text()

        self.assertIn("source_run_id:", proof)
        self.assertIn("run-id: ${{ inputs.source_run_id }}", proof)
        self.assertIn("needs.actions-cache.result == 'success' || inputs.source_run_id != ''", proof)
        self.assertIn("if: inputs.source_run_id == ''", boringcache)
        self.assertIn("CACHE_COHORT_RUN_ID: ${{ inputs.source_run_id || github.run_id }}", boringcache)
        self.assertIn(
            './scripts/scope_boringcache_plan.py xcode "$CACHE_COHORT_RUN_ID" "$CACHE_COHORT_RUN_ATTEMPT"',
            boringcache,
        )

    def test_dispatchable_product_workflows_forward_one_exact_cli_canary(self):
        proof = (ROOT / ".github" / "workflows" / "obs-compiler-cache-proof.yml").read_text()
        candidate = (ROOT / ".github" / "workflows" / "obs-boringcache.yml").read_text()
        continuation = (ROOT / ".github" / "workflows" / "obs-xcode-continuation.yml").read_text()

        self.assertIn("cli_version:", proof)
        self.assertGreaterEqual(proof.count("cli_version: ${{ inputs.cli_version }}"), 2)
        self.assertIn("cli_version:", candidate)
        self.assertEqual(candidate.count("cli-version: ${{ inputs.cli_version }}"), 4)
        self.assertIn("cli_version:", continuation)
        self.assertEqual(continuation.count("cli-version: ${{ inputs.cli_version }}"), 1)

    def test_continuation_workflow_uses_fresh_runners_and_evolving_caches(self):
        source = (ROOT / ".github" / "workflows" / "obs-xcode-continuation.yml").read_text()
        self.assertEqual(source.count("runs-on: macos-26"), 2)
        self.assertIn("fail-on-cache-miss: true", source)
        self.assertIn("actions/cache/save@", source)
        self.assertNotIn("continuation_branch:", source)
        self.assertIn("trust-policy: publish", source)
        self.assertIn("fail-on-cache-error: true", source)
        self.assertIn("steps.cache.outputs.evidence-path", source)
        driver = (ROOT / "scripts" / "run-xcode-continuation.sh").read_text()
        self.assertIn("gh run watch", driver)
        self.assertIn('restore_key="$save_key"', driver)


class ContinuationComparisonTest(unittest.TestCase):
    def test_compares_one_exact_generation(self):
        results = {}
        for strategy, seconds in (("actions-cache", 170), ("boringcache", 150)):
            results[strategy] = {
                "generation": 2,
                "project": {
                    "repository": "obsproject/obs-studio",
                    "parent_sha": "a" * 40,
                    "source_sha": "b" * 40,
                },
                "timing": {
                    "restore_seconds": 10,
                    "build_seconds": seconds,
                    "restore_and_build_seconds": seconds + 10,
                },
                "native": None,
            }
        payload = render_continuation.comparison_payload(results)
        self.assertEqual(payload["comparison"]["boringcache_seconds_saved"], 20)
        self.assertIn("**20s**", render_continuation.render_markdown(payload))


class SourcePreparationTest(unittest.TestCase):
    def test_pins_a_semantic_obs_version_for_both_providers(self):
        source = (ROOT / "benchmark-source.env").read_text()
        prepare = (ROOT / "scripts" / "prepare-obs.sh").read_text()

        self.assertIn("OBS_VERSION_OVERRIDE=32.2.0", source)
        self.assertEqual(prepare.count("-DOBS_VERSION_OVERRIDE:STRING"), 2)
        self.assertIn('source "$root/benchmark-source.env"', prepare)

    def test_xcode_build_uses_a_generated_scheme_and_absolute_log_path(self):
        prepare = (ROOT / "scripts" / "prepare-obs.sh").read_text()
        build = (ROOT / "scripts" / "run-obs-build.sh").read_text()

        self.assertIn("-DCMAKE_XCODE_GENERATE_SCHEME:BOOL=ON", prepare)
        self.assertIn("-scheme obs-studio", build)
        self.assertNotIn("\n    -target obs-studio", build)
        self.assertIn('log_path="$root/$log_path"', build)


if __name__ == "__main__":
    unittest.main()
