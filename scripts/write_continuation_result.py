#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from write_phase_result import validate_product_refs, xcode_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True, choices=("actions-cache", "boringcache"))
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--parent-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--restore-seconds", required=True, type=int)
    parser.add_argument("--build-seconds", required=True, type=int)
    parser.add_argument("--save-seconds", default=0, type=int)
    parser.add_argument("--restore-key", required=True)
    parser.add_argument("--save-key", required=True)
    parser.add_argument("--cache-bytes-before", default=0, type=int)
    parser.add_argument("--cache-bytes-after", default=0, type=int)
    parser.add_argument("--native-evidence")
    parser.add_argument("--output-dir", default="benchmark-results")
    return parser.parse_args()


def load_native(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text())


def result_payload(args: argparse.Namespace) -> dict[str, Any]:
    action_sha = os.environ.get("BORINGCACHE_ACTION_SHA", "")
    action_version = os.environ.get("BORINGCACHE_ACTION_VERSION", "")
    cli_version = os.environ.get("BORINGCACHE_CLI_VERSION", "")
    validate_product_refs(action_sha, action_version, cli_version)
    native = load_native(args.native_evidence)
    return {
        "schema_version": 1,
        "benchmark": "obs-studio-xcode-continuation",
        "surface": "xcode",
        "strategy": args.strategy,
        "generation": args.generation,
        "project": {
            "repository": "obsproject/obs-studio",
            "parent_sha": args.parent_sha,
            "source_sha": args.source_sha,
        },
        "timing": {
            "restore_seconds": args.restore_seconds,
            "build_seconds": args.build_seconds,
            "save_seconds": args.save_seconds,
            "restore_and_build_seconds": args.restore_seconds + args.build_seconds,
            "end_to_end_seconds": args.restore_seconds + args.build_seconds + args.save_seconds,
        },
        "cache": {
            "restore_key": args.restore_key,
            "save_key": args.save_key,
            "bytes_before": args.cache_bytes_before,
            "bytes_after": args.cache_bytes_after,
            "growth_bytes": max(0, args.cache_bytes_after - args.cache_bytes_before),
        },
        "native": xcode_summary(native),
        "product_refs": {
            "action_sha": action_sha,
            "action_version": action_version,
            "cli_version": cli_version,
        },
        "classification": {
            "sample_valid": True,
            "reporting_mode": "continuation",
            "cache_import_status": "hit",
            "reporting_reason": "fresh runner restored the previous generation and built its exact child commit",
        },
        "github": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
        },
    }


def main() -> int:
    args = parse_args()
    payload = result_payload(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"continuation-{args.strategy}.json"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
