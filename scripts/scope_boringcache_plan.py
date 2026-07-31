#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def scoped_plan(source: str, surface: str, run_id: str, run_attempt: str) -> str:
    section = re.compile(
        rf"(^\[adapters\.{re.escape(surface)}\]\n)(.*?)(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = section.search(source)
    if not match:
        raise ValueError(f"missing [adapters.{surface}] section")

    body = match.group(2)
    tag = f"obs-studio-{surface}-r{run_id}-a{run_attempt}"
    replaced, count = re.subn(
        r'^tag\s*=\s*"[^"]+"\s*$',
        f'tag = "{tag}"',
        body,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"[adapters.{surface}] must contain exactly one tag")
    return source[: match.start(2)] + replaced + source[match.end(2) :]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=("ccache", "xcode"))
    parser.add_argument("run_id")
    parser.add_argument("run_attempt")
    parser.add_argument("--plan", default=".boringcache.toml")
    args = parser.parse_args()

    path = Path(args.plan)
    path.write_text(scoped_plan(path.read_text(), args.surface, args.run_id, args.run_attempt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
