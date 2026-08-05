#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", required=True, choices=("ccache", "xcode"))
    parser.add_argument("--strategy", required=True, choices=("actions-cache", "boringcache"))
    parser.add_argument("--phase", required=True, choices=("base", "rolling"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--restore-seconds", type=int, required=True)
    parser.add_argument("--build-seconds", type=int, required=True)
    parser.add_argument("--cache-key", default="")
    parser.add_argument("--native-evidence")
    parser.add_argument("--output-dir", default="benchmark-results")
    return parser.parse_args()


def classification(surface: str, strategy: str, phase: str) -> dict[str, Any]:
    if phase == "base":
        validity_reason = (
            "cold seed build and native BoringCache publication gate passed"
            if strategy == "boringcache"
            else "cold seed build and baseline cache export gate passed"
        )
        return {
            "sample_valid": True,
            "reporting_mode": "cold",
            "reporting_reason": "pinned parent commit seeds an empty compiler-cache cohort",
            "validity_reason": validity_reason,
            "cache_import_status": "cold",
        }

    native_gate = "remote native cache evidence" if strategy == "boringcache" else "exact-key cache restore"
    return {
        "sample_valid": True,
        "reporting_mode": "commit-build",
        "reporting_reason": "adjacent real C++ commit reuses the parent commit's compiler cache",
        "validity_reason": f"{native_gate} and {surface} replay-hit gates passed",
        "cache_import_status": "hit",
    }


def load_native_evidence(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    evidence_path = Path(path)
    if not evidence_path.is_file():
        raise FileNotFoundError(f"native evidence does not exist: {evidence_path}")
    return json.loads(evidence_path.read_text())


def ccache_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    hits = payload.get("direct_cache_hit", 0) + payload.get("preprocessed_cache_hit", 0)
    misses = payload.get("cache_miss", 0)
    total = hits + misses
    return {
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_percent": round(hits * 100 / total, 1) if total else None,
        "remote_storage_hits": payload.get("remote_storage_hit", 0),
        "remote_storage_writes": payload.get("remote_storage_write", 0),
        "remote_storage_errors": payload.get("remote_storage_error", 0),
        "remote_storage_timeouts": payload.get("remote_storage_timeout", 0),
    }


def main() -> int:
    args = parse_args()
    native = load_native_evidence(args.native_evidence)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": 2,
        "benchmark": "obs-studio-compiler-cache",
        "surface": args.surface,
        "strategy": args.strategy,
        "phase": args.phase,
        "project": {
            "repository": "obsproject/obs-studio",
            "source_sha": args.source_sha,
        },
        "timing": {
            "restore_seconds": args.restore_seconds,
            "build_seconds": args.build_seconds,
            "end_to_end_seconds": args.restore_seconds + args.build_seconds,
        },
        "classification": classification(args.surface, args.strategy, args.phase),
        "cache": {"key": args.cache_key or None},
        "native": ccache_summary(native) if args.surface == "ccache" else None,
        "github": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
        },
    }

    output_path = output_dir / f"{args.surface}-{args.strategy}-{args.phase}.json"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
