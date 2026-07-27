#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SURFACES = ("ccache", "xcode")
STRATEGIES = ("actions-cache", "boringcache")
PHASES = ("base", "rolling")
EXPECTED_RESULTS = {
    (surface, strategy, phase)
    for surface in SURFACES
    for strategy in STRATEGIES
    for phase in PHASES
}


def validate_result(payload: dict[str, Any], path: Path) -> None:
    if payload.get("schema_version") != 2:
        raise ValueError(f"unsupported or missing result schema in {path}")
    classification = payload.get("classification") or {}
    if classification.get("sample_valid") is not True:
        raise ValueError(f"invalid benchmark sample in {path}: {classification.get('validity_reason')}")
    for field in ("reporting_mode", "reporting_reason", "validity_reason", "cache_import_status"):
        if not classification.get(field):
            raise ValueError(f"missing classification.{field} in {path}")
    product_refs = payload.get("product_refs") or {}
    if not re.fullmatch(r"[0-9a-f]{40}", str(product_refs.get("action_sha", ""))):
        raise ValueError(f"missing immutable Action SHA in {path}")
    for field in ("action_version", "cli_version"):
        if not re.fullmatch(r"v\d+\.\d+\.\d+", str(product_refs.get(field, ""))):
            raise ValueError(f"missing stable product_refs.{field} in {path}")


def load_results(input_dir: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    results: dict[tuple[str, str, str], dict[str, Any]] = {}
    missing: list[tuple[str, str, str]] = []
    for key in sorted(EXPECTED_RESULTS):
        surface, strategy, phase = key
        path = input_dir / f"{surface}-{strategy}-{phase}.json"
        if not path.is_file():
            missing.append(key)
            continue
        payload = json.loads(path.read_text())
        validate_result(payload, path)
        actual_key = (payload["surface"], payload["strategy"], payload["phase"])
        if actual_key != key:
            raise ValueError(f"benchmark result identity mismatch in {path}: {actual_key}")
        results[key] = payload

    if missing:
        labels = ", ".join("/".join(key) for key in sorted(missing))
        raise ValueError(f"missing benchmark results: {labels}")
    product_refs = {json.dumps(payload["product_refs"], sort_keys=True) for payload in results.values()}
    if len(product_refs) != 1:
        raise ValueError("benchmark results do not share one exact CLI and Action release cohort")
    return results


def surface_comparison(
    results: dict[tuple[str, str, str], dict[str, Any]], surface: str
) -> dict[str, Any]:
    baseline = results[(surface, "actions-cache", "rolling")]["timing"]
    candidate = results[(surface, "boringcache", "rolling")]["timing"]
    baseline_total = baseline["end_to_end_seconds"]
    candidate_total = candidate["end_to_end_seconds"]
    saved = baseline_total - candidate_total
    return {
        "actions_cache_end_to_end_seconds": baseline_total,
        "boringcache_end_to_end_seconds": candidate_total,
        "end_to_end_seconds_saved": saved,
        "percent_saved": round(saved * 100 / baseline_total, 1) if baseline_total else None,
        "actions_cache_build_seconds": baseline["build_seconds"],
        "boringcache_build_seconds": candidate["build_seconds"],
        "build_seconds_saved": baseline["build_seconds"] - candidate["build_seconds"],
    }


def comparison_payload(
    results: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "benchmark": "obs-studio-compiler-cache",
        "classification": {
            "sample_valid": True,
            "reporting_mode": "commit-build",
            "reporting_reason": "all eight hard-gated phase samples share one exact product cohort",
            "validity_reason": "every phase result passed its cache import and native replay gates",
            "cache_import_status": "hit",
        },
        "product_refs": next(iter(results.values()))["product_refs"],
        "results": [results[key] for key in sorted(results)],
        "rolling_comparison": {
            surface: surface_comparison(results, surface) for surface in SURFACES
        },
    }


def format_seconds(value: int | None) -> str:
    return "n/a" if value is None else f"{value}s"


def native_result(row: dict[str, Any]) -> str:
    native = row.get("native") or {}
    if row["surface"] == "ccache":
        rate = native.get("cache_hit_percent")
        remote_hits = native.get("remote_storage_hits")
        details = "n/a" if rate is None else f"{rate}% compiler hits"
        if row["strategy"] == "boringcache" and remote_hits is not None:
            details += f"; {remote_hits} remote hits"
        return details
    hits = native.get("action_hits")
    fetched = native.get("bytes_fetched")
    if hits is None:
        return "CAS restored; Xcode does not expose equivalent baseline counters"
    return f"{hits} action hits; {fetched} bytes fetched"


def conclusion(surface: str, comparison: dict[str, Any]) -> str:
    saved = comparison["end_to_end_seconds_saved"]
    if saved > 0:
        return f"BoringCache saved **{saved}s ({comparison['percent_saved']}%)**."
    if saved < 0:
        return f"BoringCache was **{-saved}s slower**; this run does not support migration."
    return "Restore-plus-build times were equal."


def render_markdown(payload: dict[str, Any]) -> str:
    indexed = {
        (row["surface"], row["strategy"], row["phase"]): row
        for row in payload["results"]
    }
    lines = [
        "# OBS Studio compiler-cache proof",
        "",
        "Pinned adjacent pair: `6750a6e` → `f730063` (real frontend C++ change).",
        "",
        "| Surface | Strategy | Phase | Restore/setup | Build | End-to-end | Native evidence |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for surface in SURFACES:
        for strategy in STRATEGIES:
            for phase in PHASES:
                row = indexed[(surface, strategy, phase)]
                timing = row["timing"]
                lines.append(
                    "| {surface} | {strategy} | {phase} | {restore} | {build} | {total} | {native} |".format(
                        surface=surface,
                        strategy=strategy,
                        phase=phase,
                        restore=format_seconds(timing.get("restore_seconds")),
                        build=format_seconds(timing.get("build_seconds")),
                        total=format_seconds(timing.get("end_to_end_seconds")),
                        native=native_result(row),
                    )
                )

    lines.extend(["", "## Rolling result", ""])
    for surface in SURFACES:
        comparison = payload["rolling_comparison"][surface]
        lines.append(f"- **{surface}:** {conclusion(surface, comparison)}")
    lines.extend(
        [
            "",
            "Dependency installation and CMake generation are outside the timer. Both lanes build OBS's `obs-studio` target on fresh runners; only cache setup/restore and compilation are compared.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    results = load_results(Path(args.input_dir))
    payload = comparison_payload(results)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "comparison.md").write_text(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
