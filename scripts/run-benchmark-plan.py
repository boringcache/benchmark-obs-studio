#!/usr/bin/env python3
"""Run one adapter command from the committed BoringCache plan."""

from __future__ import annotations

import argparse
import os
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("adapter")
    parser.add_argument("--working-directory", default=".")
    args = parser.parse_args()

    plan = tomllib.loads((ROOT / ".boringcache.toml").read_text())
    command = plan["adapters"][args.adapter].get("command")
    if not isinstance(command, list) or not command:
        parser.error(f"adapters.{args.adapter}.command must be a non-empty argv array")

    working_directory = (ROOT / args.working_directory).resolve()
    working_directory.relative_to(ROOT)
    env = os.environ.copy()
    env.setdefault("GITHUB_EVENT_NAME", "workflow_dispatch")
    env.setdefault("GITHUB_REF_NAME", "benchmark")
    return subprocess.run(command, cwd=working_directory, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
