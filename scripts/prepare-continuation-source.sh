#!/usr/bin/env bash
set -euo pipefail

source_sha="${1:-}"
parent_sha="${2:-}"
if [[ ! "$source_sha" =~ ^[0-9a-f]{40}$ ]] || [[ ! "$parent_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 SOURCE_SHA PARENT_SHA" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
upstream="$root/upstream"

git -C "$upstream" cat-file -e "${source_sha}^{commit}"
git -C "$upstream" cat-file -e "${parent_sha}^{commit}"

actual_parent="$(git -C "$upstream" rev-parse "${source_sha}^")"
if [[ "$actual_parent" != "$parent_sha" ]]; then
  echo "Continuation commits are not an adjacent parent/child pair." >&2
  echo "expected parent: $parent_sha" >&2
  echo "actual parent:   $actual_parent" >&2
  exit 1
fi

git -C "$upstream" checkout --detach "$source_sha"
git -C "$upstream" submodule sync --recursive
git -C "$upstream" submodule update --init --recursive

resolved="$(git -C "$upstream" rev-parse HEAD)"
if [[ "$resolved" != "$source_sha" ]]; then
  echo "OBS checkout resolved to $resolved instead of $source_sha" >&2
  exit 1
fi

echo "Prepared OBS Studio continuation source at $resolved"
python3 "$root/scripts/verify-upstream-recipe.py"
