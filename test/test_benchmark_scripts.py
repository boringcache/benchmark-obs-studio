from __future__ import annotations

import importlib.util
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
render_continuation = load_script("render_continuation.py")
write_result = load_script("write_phase_result.py")


class SourceSyncTest(unittest.TestCase):
    def test_skips_workflow_only_commits_and_selects_an_adjacent_source_pair(self):
        current = "a" * 40
        workflow_only = "b" * 40
        following = "c" * 40
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
                f"echo '{{\"status\":\"ahead\",\"commits\":[{{\"sha\":\"{workflow_only}\"}},{{\"sha\":\"{following}\"}}]}}' ;;\n"
                f"  'api repos/obsproject/obs-studio/commits/{workflow_only} --jq .files[].filename') echo .github/workflows/push.yaml ;;\n"
                f"  'api repos/obsproject/obs-studio/commits/{following} --jq .files[].filename') echo frontend/obs-main.cpp ;;\n"
                f"  'api repos/obsproject/obs-studio/commits/{following} --jq .parents[0].sha // empty') echo {workflow_only} ;;\n"
                "  *) echo \"Unexpected gh call: $*\" >&2; exit 1 ;;\n"
                "esac\n"
            )
            gh.chmod(0o755)
            subprocess.run(
                [str(ROOT / "scripts/advance-source-pair.sh"), str(source), "OBS"],
                check=True,
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            )
            settings = dict(line.split("=", 1) for line in source.read_text().splitlines())

        self.assertEqual(settings["OBS_BASE_SHA"], workflow_only)
        self.assertEqual(settings["OBS_HEAD_SHA"], following)
        self.assertEqual(settings["OBS_VERSION_OVERRIDE"], "32.2.0")


class PlanScopingTest(unittest.TestCase):
    def test_scopes_only_the_selected_adapter(self):
        source = (ROOT / ".boringcache.toml").read_text()
        result = scope_plan.scoped_plan(source, "xcode", "42", "3")
        self.assertIn('tag = "obs-studio-xcode-r42-a3"', result)
        self.assertIn('tag = "obs-studio-ccache"', result)


class NativeEvidenceTest(unittest.TestCase):
    def test_requires_native_remote_ccache_hit_on_rolling_build(self):
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

    def test_accepts_raw_and_upstream_formatted_xcode_compilation(self):
        verify_xcode_log.validate("CompileC object.o source.cpp\n")
        verify_xcode_log.validate("[libobs] \x1b[1mCompiling\x1b[0m obs-source.c\n")
        with self.assertRaisesRegex(ValueError, "native compilation"):
            verify_xcode_log.validate("[libobs] Linking libobs\n")


class ResultContractTest(unittest.TestCase):
    def test_result_classification_is_fail_closed(self):
        rolling = write_result.classification("ccache", "boringcache", "rolling")
        self.assertTrue(rolling["sample_valid"])
        self.assertEqual(rolling["reporting_mode"], "commit-build")
        self.assertEqual(rolling["cache_import_status"], "hit")

    def test_action_cache_key_comes_from_the_evidence_file(self):
        evidence = {"phases": {"restore": {"cache_tag": "obs-ccache-r42"}}}
        self.assertEqual(write_result.action_cache_key(evidence), "obs-ccache-r42")


class WorkflowContractTest(unittest.TestCase):
    def test_source_updates_dispatch_both_current_provider_workflows(self):
        baseline = (ROOT / ".github/workflows/obs-actions-cache.yml").read_text()
        candidate = (ROOT / ".github/workflows/obs-boringcache.yml").read_text()
        sync = (ROOT / ".github/workflows/sync.yml").read_text()

        self.assertIn('paths: ["benchmark-source.env"]', baseline)
        self.assertIn('paths: ["benchmark-source.env"]', candidate)
        self.assertIn('cron: "18,48 * * * *"', sync)
        self.assertIn("advance-source-pair.sh benchmark-source.env OBS", sync)

    def test_every_primary_build_executes_the_committed_plan(self):
        baseline = (ROOT / ".github/workflows/obs-actions-cache.yml").read_text()
        candidate = (ROOT / ".github/workflows/obs-boringcache.yml").read_text()
        self.assertEqual(baseline.count("run-benchmark-plan.py"), 4)
        self.assertEqual(candidate.count("run-benchmark-plan.py"), 4)
        self.assertEqual(candidate.count("boringcache/one@c62af42c5c1e29388ceeea77b6a7f1db51f641e7"), 4)
        self.assertEqual(candidate.count("cli-version: ${{ inputs.cli_version }}"), 4)
        self.assertEqual(candidate.count("Install the benchmark ccache release"), 2)
        self.assertNotIn("setup: none", candidate)
        self.assertNotIn("ccache-version:", candidate)
        self.assertNotIn("metadata-hints:", candidate)
        self.assertEqual(candidate.count("working-directory: ./upstream"), 4)
        self.assertNotIn("BORINGCACHE_API_TOKEN", candidate)

    def test_xcode_continuation_uses_the_same_plan_and_evolving_cache(self):
        workflow = (ROOT / ".github/workflows/obs-xcode-continuation.yml").read_text()
        self.assertEqual(workflow.count("runs-on: macos-26"), 2)
        self.assertEqual(workflow.count("run-benchmark-plan.py xcode"), 2)
        self.assertIn("fail-on-cache-miss: true", workflow)
        self.assertIn("actions/cache/save@", workflow)
        self.assertIn("trust-policy: publish", workflow)
        self.assertIn("fail-on-cache-error: true", workflow)
        driver = (ROOT / "scripts/run-xcode-continuation.sh").read_text()
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


class UpstreamRecipeTest(unittest.TestCase):
    def test_committed_plan_runs_upstreams_build_wrappers(self):
        plan = (ROOT / ".boringcache.toml").read_text()
        self.assertIn(
            'command = [".github/scripts/build-ubuntu", "--config", '
            '"RelWithDebInfo", "--target", "ubuntu-x86_64"]',
            plan,
        )
        self.assertIn(
            'command = [".github/scripts/build-macos", "--config", '
            '"RelWithDebInfo", "--target", "macos-arm64"]',
            plan,
        )

    def test_workflows_do_not_reimplement_upstream_builds(self):
        workflows = "\n".join(
            path.read_text() for path in (ROOT / ".github/workflows").glob("obs-*.yml")
        )
        self.assertIn("run-benchmark-plan.py ccache", workflows)
        self.assertIn("run-benchmark-plan.py xcode", workflows)
        self.assertNotIn("prepare-obs.sh", workflows)
        self.assertNotIn("run-obs-build.sh", workflows)


if __name__ == "__main__":
    unittest.main()
