#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any


def evidence_ready(payload: dict[str, Any], phase: str) -> bool:
    if payload.get("schema") != "boringcache.xcode.v1":
        return False
    if payload.get("action_errors", 0) or payload.get("publications_failed", 0):
        return False
    if phase == "base":
        return (
            payload.get("actions_published", 0) > 0
            and payload.get("objects_published", 0) > 0
            and payload.get("bytes_published", 0) > 0
        )
    if phase == "continuation":
        return (
            payload.get("action_hits", 0) > 0
            and payload.get("actions_warmed", 0) > 0
            and payload.get("objects_warmed", 0) > 0
            and payload.get("objects_materialized", 0) > 0
            and payload.get("warmup_bytes", 0) > 0
            and payload.get("warmup_failures", 0) == 0
            and payload.get("objects_fetched", 0) == 0
            and payload.get("bytes_fetched", 0) == 0
        )
    return (
        payload.get("action_hits", 0) > 0
        and payload.get("actions_warmed", 0) > 0
        and payload.get("objects_warmed", 0) > 0
        and payload.get("objects_materialized", 0) > 0
        and payload.get("warmup_bytes", 0) > 0
        and payload.get("warmup_failures", 0) == 0
        and payload.get("objects_fetched", 0) == 0
        and payload.get("bytes_fetched", 0) == 0
        and payload.get("actions_published", 0) == 0
    )


def wait_for_evidence(path: Path, phase: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(1)
            continue
        last_payload = payload
        if evidence_ready(payload, phase):
            return payload
        time.sleep(1)
    raise TimeoutError(
        f"Xcode {phase} evidence was not ready after {timeout}s; last payload={last_payload}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument(
        "--phase", required=True, choices=("base", "rolling", "continuation")
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    source = Path(args.path)
    payload = wait_for_evidence(source, args.phase, args.timeout)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
