#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
FORMATTED_COMPILE = re.compile(
    r"]\s+compiling\s+\S+\.(?:c|cc|cpp|cxx|m|mm|swift)(?:\s|$)",
    re.IGNORECASE,
)


def validate(source: str) -> None:
    normalized = ANSI_ESCAPE.sub("", source)
    lowered = normalized.lower()
    if (
        "compilec " not in lowered
        and " clang " not in lowered
        and FORMATTED_COMPILE.search(normalized) is None
    ):
        raise ValueError("rolling Xcode build did not exercise native compilation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    validate(Path(args.path).read_text(errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
