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
write_result = load_script("write_phase_result.py")


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
    def test_requires_restore_only_remote_evidence(self):
        payload = {
            "schema": "boringcache.xcode.v1",
            "action_hits": 12,
            "action_errors": 0,
            "actions_published": 0,
            "objects_fetched": 30,
            "bytes_fetched": 4096,
            "publications_failed": 0,
        }
        self.assertTrue(wait_xcode.evidence_ready(payload, "rolling"))
        payload["actions_published"] = 1
        self.assertFalse(wait_xcode.evidence_ready(payload, "rolling"))

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


if __name__ == "__main__":
    unittest.main()
