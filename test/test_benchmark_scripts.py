from __future__ import annotations

import importlib.util
import json
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
wait_xcode = load_script("wait_for_xcode_evidence.py")
verify_xcode_log = load_script("verify_xcode_build_log.py")
render = load_script("render_comparison.py")
render_continuation = load_script("render_continuation.py")
write_result = load_script("write_phase_result.py")


class PlanScopingTest(unittest.TestCase):
    def test_scopes_only_the_selected_adapter(self):
        source = (ROOT / ".boringcache.toml").read_text()
        result = scope_plan.scoped_plan(source, "xcode", "42", "3")
        self.assertIn('tag = "obs-studio-xcode-r42-a3"', result)
        self.assertIn('tag = "obs-studio-ccache"', result)

    def test_git_aware_scope_preserves_seed_as_branch_fallback(self):
        source = (ROOT / ".boringcache.toml").read_text()
        result = scope_plan.scoped_plan(
            source, "xcode", "42", "3", git_aware=True
        )
        xcode = result.split("[adapters.xcode]", 1)[1]
        self.assertIn('tag = "obs-studio-xcode-r42-a3"', xcode)
        self.assertIn("no-git = false", xcode)
        self.assertIn("[adapters.ccache]\ntag = \"obs-studio-ccache\"\nno-git = true", result)


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
    def test_requires_complete_eager_warm_restore_evidence(self):
        payload = {
            "schema": "boringcache.xcode.v1",
            "action_hits": 12,
            "action_errors": 0,
            "actions_published": 0,
            "actions_warmed": 12,
            "objects_warmed": 30,
            "objects_materialized": 30,
            "warmup_bytes": 4096,
            "warmup_failures": 0,
            "objects_fetched": 0,
            "bytes_fetched": 0,
            "publications_failed": 0,
        }
        self.assertTrue(wait_xcode.evidence_ready(payload, "rolling"))
        payload["warmup_failures"] = 1
        self.assertFalse(wait_xcode.evidence_ready(payload, "rolling"))
        payload["warmup_failures"] = 0
        payload["objects_fetched"] = 1
        self.assertFalse(wait_xcode.evidence_ready(payload, "rolling"))

    def test_result_preserves_eager_warm_and_zero_demand_counters(self):
        summary = write_result.xcode_summary(
            {
                "action_hits": 12,
                "actions_warmed": 12,
                "objects_warmed": 30,
                "objects_materialized": 30,
                "warmup_bytes": 4096,
                "warmup_failures": 0,
                "objects_fetched": 0,
                "bytes_fetched": 0,
            }
        )
        self.assertEqual(summary["objects_materialized"], 30)
        self.assertEqual(summary["warmup_bytes"], 4096)
        self.assertEqual(summary["bytes_fetched"], 0)

    def test_continuation_allows_publication_but_not_demand_fetches(self):
        payload = {
            "schema": "boringcache.xcode.v1",
            "action_hits": 12,
            "action_errors": 0,
            "actions_published": 2,
            "actions_warmed": 12,
            "objects_warmed": 30,
            "objects_materialized": 30,
            "warmup_bytes": 4096,
            "warmup_failures": 0,
            "objects_fetched": 0,
            "bytes_fetched": 0,
            "publications_failed": 0,
        }
        self.assertTrue(wait_xcode.evidence_ready(payload, "continuation"))
        payload["objects_fetched"] = 1
        self.assertFalse(wait_xcode.evidence_ready(payload, "continuation"))

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
                        "product_refs": {
                            "action_sha": "a" * 40,
                            "action_version": "v1.14.0",
                            "cli_version": "v1.14.0",
                        },
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
                        "product_refs": {
                            "action_sha": "a" * 40,
                            "action_version": "v1.14.0",
                            "cli_version": "v1.14.0",
                        },
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


class WorkflowTemplateTest(unittest.TestCase):
    def test_boringcache_template_uses_current_adapter_contract(self):
        source = (ROOT / "workflow-templates" / "obs-boringcache.yml").read_text()
        self.assertEqual(source.count("boringcache/one@__BORINGCACHE_ONE_SHA__"), 4)
        self.assertEqual(source.count("setup: none"), 4)
        self.assertEqual(source.count("mode: ccache"), 2)
        self.assertEqual(source.count("ccache-version: 4.13.6"), 2)
        self.assertEqual(source.count("mode: xcode"), 2)
        self.assertEqual(source.count("trust-policy: publish"), 2)
        self.assertEqual(source.count("trust-policy: restore"), 2)
        self.assertEqual(source.count("working-directory: ./upstream"), 4)
        self.assertEqual(source.count("# __BORINGCACHE_ONE_VERSION__"), 4)
        self.assertNotIn("BORINGCACHE_API_TOKEN", source)
        self.assertNotIn("cache-tag:", source)
        self.assertNotIn("read-only:", source)

    def test_result_classification_is_fail_closed(self):
        rolling = write_result.classification("ccache", "boringcache", "rolling")
        self.assertTrue(rolling["sample_valid"])
        self.assertEqual(rolling["reporting_mode"], "commit-build")
        self.assertEqual(rolling["cache_import_status"], "hit")
        write_result.validate_product_refs("a" * 40, "v1.14.0", "v1.14.0")
        with self.assertRaisesRegex(ValueError, "immutable 40-character"):
            write_result.validate_product_refs("v1", "v1.14.0", "v1.14.0")

    def test_focused_xcode_recovery_reuses_one_immutable_cohort(self):
        proof = (ROOT / "workflow-templates" / "obs-compiler-cache-proof.yml").read_text()
        boringcache = (ROOT / "workflow-templates" / "obs-boringcache.yml").read_text()

        self.assertIn("source_run_id:", proof)
        self.assertIn("run-id: ${{ inputs.source_run_id }}", proof)
        self.assertIn("needs.actions-cache.result == 'success' || inputs.source_run_id != ''", proof)
        self.assertIn("if: inputs.source_run_id == ''", boringcache)
        self.assertIn("CACHE_COHORT_RUN_ID: ${{ inputs.source_run_id || github.run_id }}", boringcache)
        self.assertIn(
            './scripts/scope_boringcache_plan.py xcode "$CACHE_COHORT_RUN_ID" "$CACHE_COHORT_RUN_ATTEMPT"',
            boringcache,
        )

    def test_active_workflows_are_rendered_from_templates(self):
        replacements = {
            "__BORINGCACHE_ONE_SHA__": "8294be671cd5a2b73638df1b8e1e240df888297e",
            "__BORINGCACHE_ONE_VERSION__": "v1.15.0",
            "__BORINGCACHE_CLI_VERSION__": "v1.15.0",
        }
        for template in (ROOT / "workflow-templates").glob("*.yml"):
            expected = template.read_text()
            for source, target in replacements.items():
                expected = expected.replace(source, target)
            active = (ROOT / ".github" / "workflows" / template.name).read_text()
            self.assertEqual(active, expected, template.name)

    def test_continuation_workflow_uses_fresh_runners_and_evolving_caches(self):
        source = (ROOT / "workflow-templates" / "obs-xcode-continuation.yml").read_text()
        self.assertEqual(source.count("runs-on: macos-26"), 2)
        self.assertIn("fail-on-cache-miss: true", source)
        self.assertIn("actions/cache/save@", source)
        self.assertIn("--git-aware", source)
        self.assertIn("BORINGCACHE_GIT_BRANCH", source)
        self.assertIn("--phase continuation", source)
        self.assertIn("trust-policy: publish", source)
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
