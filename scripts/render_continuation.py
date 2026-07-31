#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STRATEGIES = ("actions-cache", "boringcache")


def load_results(input_dir: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        matches = list(input_dir.rglob(f"continuation-{strategy}.json"))
        if len(matches) != 1:
            raise ValueError(f"expected one {strategy} continuation result, found {len(matches)}")
        payload = json.loads(matches[0].read_text())
        if not payload.get("classification", {}).get("sample_valid"):
            raise ValueError(f"{strategy} continuation sample is not valid")
        results[strategy] = payload

    actions = results["actions-cache"]
    boringcache = results["boringcache"]
    for field in ("generation",):
        if actions[field] != boringcache[field]:
            raise ValueError(f"continuation results disagree on {field}")
    if actions["project"] != boringcache["project"]:
        raise ValueError("continuation results use different source commits")
    return results


def comparison_payload(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    actions = results["actions-cache"]
    boringcache = results["boringcache"]
    actions_total = actions["timing"]["restore_and_build_seconds"]
    boringcache_total = boringcache["timing"]["restore_and_build_seconds"]
    return {
        "schema_version": 1,
        "benchmark": "obs-studio-xcode-continuation",
        "generation": actions["generation"],
        "project": actions["project"],
        "sample_valid": True,
        "results": results,
        "comparison": {
            "actions_cache_restore_and_build_seconds": actions_total,
            "boringcache_restore_and_build_seconds": boringcache_total,
            "boringcache_seconds_saved": actions_total - boringcache_total,
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    rows = []
    for strategy in STRATEGIES:
        result = payload["results"][strategy]
        timing = result["timing"]
        native = result.get("native") or {}
        rows.append(
            f"| {strategy} | {timing['restore_seconds']}s | {timing['build_seconds']}s | "
            f"{timing['restore_and_build_seconds']}s | {native.get('action_hits', 'n/a')} | "
            f"{native.get('action_misses', 'n/a')} |"
        )
    comparison = payload["comparison"]
    return "\n".join(
        [
            f"## OBS Xcode continuation generation {payload['generation']}",
            "",
            "| Strategy | Restore | Build | Restore + build | Native hits | Native misses |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            f"BoringCache seconds saved: **{comparison['boringcache_seconds_saved']}s**.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    results = load_results(Path(args.input_dir))
    payload = comparison_payload(results)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "continuation-comparison.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "continuation-comparison.md").write_text(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
