#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(payload: dict[str, Any], phase: str, strategy: str) -> None:
    errors = payload.get("remote_storage_error", 0)
    timeouts = payload.get("remote_storage_timeout", 0)
    if errors or timeouts:
        raise ValueError(f"ccache reported remote errors={errors}, timeouts={timeouts}")

    hits = payload.get("direct_cache_hit", 0) + payload.get("preprocessed_cache_hit", 0)
    misses = payload.get("cache_miss", 0)
    if phase == "base" and misses <= 0:
        raise ValueError("cold ccache build did not report any cache misses")
    if phase == "rolling" and hits <= 0:
        raise ValueError("rolling ccache build did not report any cache hits")

    if strategy == "boringcache":
        remote_hits = payload.get("remote_storage_hit", 0)
        remote_writes = payload.get("remote_storage_write", 0)
        if phase == "base" and remote_writes <= 0:
            raise ValueError("BoringCache cold build did not publish remote ccache entries")
        if phase == "rolling" and remote_hits <= 0:
            raise ValueError("BoringCache rolling build did not restore remote ccache entries")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--phase", required=True, choices=("base", "rolling"))
    parser.add_argument("--strategy", required=True, choices=("actions-cache", "boringcache"))
    args = parser.parse_args()
    payload = json.loads(Path(args.path).read_text())
    validate(payload, args.phase, args.strategy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
