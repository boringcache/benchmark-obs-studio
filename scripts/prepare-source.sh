#!/usr/bin/env bash
set -euo pipefail

phase="${1:-}"
case "$phase" in
  base|rolling) ;;
  *)
    echo "usage: $0 base|rolling" >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The path is resolved from the benchmark repository root at runtime.
# shellcheck disable=SC1091
source "$root/benchmark-source.env"
upstream="$root/upstream"

git -C "$upstream" cat-file -e "${OBS_BASE_SHA}^{commit}"
git -C "$upstream" cat-file -e "${OBS_HEAD_SHA}^{commit}"

actual_parent="$(git -C "$upstream" rev-parse "${OBS_HEAD_SHA}^")"
if [[ "$actual_parent" != "$OBS_BASE_SHA" ]]; then
  echo "Pinned OBS commits are not an adjacent parent/child pair." >&2
  echo "expected parent: $OBS_BASE_SHA" >&2
  echo "actual parent:   $actual_parent" >&2
  exit 1
fi

if [[ "$phase" == "base" ]]; then
  source_sha="$OBS_BASE_SHA"
else
  source_sha="$OBS_HEAD_SHA"
fi

git -C "$upstream" checkout --detach "$source_sha"
git -C "$upstream" submodule sync --recursive
git -C "$upstream" submodule update --init --recursive

resolved="$(git -C "$upstream" rev-parse HEAD)"
if [[ "$resolved" != "$source_sha" ]]; then
  echo "OBS checkout resolved to $resolved instead of $source_sha" >&2
  exit 1
fi

echo "Prepared OBS Studio $phase source at $resolved"
python3 "$root/scripts/verify-upstream-recipe.py"
