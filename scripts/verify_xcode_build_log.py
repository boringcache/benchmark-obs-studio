#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def validate(source: str) -> None:
    lowered = source.lower()
    if "compilec " not in lowered and " clang " not in lowered:
        raise ValueError("rolling Xcode build did not exercise native compilation")
    if "replayed cache hit" not in lowered and "replay cache hit" not in lowered:
        raise ValueError("rolling Xcode build did not report a compilation-cache replay hit")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    validate(Path(args.path).read_text(errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
