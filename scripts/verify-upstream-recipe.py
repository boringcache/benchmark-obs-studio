#!/usr/bin/env python3
"""Verify OBS benchmark plans against the pinned upstream composite action."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    try:
        plan = tomllib.loads((ROOT / ".boringcache.toml").read_text())
        require(plan["adapters"]["ccache"]["command"] == [".github/scripts/build-ubuntu", "--config", "RelWithDebInfo", "--target", "ubuntu-x86_64"], "ccache command changed")
        require(plan["adapters"]["xcode"]["command"] == [".github/scripts/build-macos", "--config", "RelWithDebInfo", "--target", "macos-arm64"], "Xcode command changed")

        workflow = (ROOT / "upstream/.github/workflows/build-project.yaml").read_text()
        action = (ROOT / "upstream/.github/actions/build-obs/action.yaml").read_text()
        for fragment in ("os: [ubuntu-24.04, ubuntu-26.04]", "target: [arm64, x86_64]", "config:RelWithDebInfo", "Xcode_26.5.app"):
            require(fragment in workflow, f"upstream build matrix changed: {fragment}")
        for fragment in (".github/scripts/build-macos ${build_args}", ".github/scripts/build-ubuntu ${build_args}", "--target macos-${{ inputs.target }}", "--target ubuntu-${{ inputs.target }}"):
            require(fragment in action, f"upstream build wrapper changed: {fragment}")

        local_workflows = "\n".join(path.read_text() for path in (ROOT / ".github/workflows").glob("obs-*.yml"))
        require("run-benchmark-plan.py ccache" in local_workflows, "ccache workflow bypasses the plan")
        require("run-benchmark-plan.py xcode" in local_workflows, "Xcode workflow bypasses the plan")
        require(local_workflows.count("brew install --quiet zsh") == 4, "Linux workflows omit the upstream zsh setup")
        require('mkdir -p "$root/benchmark-results"' in (ROOT / "scripts/prepare-source.sh").read_text(), "benchmark evidence directory is not prepared")
        require("prepare-obs.sh" not in local_workflows and "run-obs-build.sh" not in local_workflows, "retired local OBS reimplementation remains")
    except (KeyError, OSError, RuntimeError, tomllib.TOMLDecodeError) as error:
        print(f"OBS recipe mismatch: {error}", file=sys.stderr)
        return 1
    print("Verified OBS ccache and Xcode plans against pinned upstream wrappers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
