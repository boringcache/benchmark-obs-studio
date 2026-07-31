#!/usr/bin/env bash
set -euo pipefail

seed_run_id="${1:-}"
seed_run_attempt="${2:-1}"
actions_seed_key="${3:-}"
chain_id="${4:-}"
start_generation="${5:-1}"
if [[ ! "$seed_run_id" =~ ^[0-9]+$ ]] || [[ ! "$seed_run_attempt" =~ ^[0-9]+$ ]] ||
   [[ -z "$actions_seed_key" ]] || [[ ! "$chain_id" =~ ^[a-z0-9][a-z0-9._-]*$ ]] ||
   [[ ! "$start_generation" =~ ^[1-9][0-9]*$ ]]; then
  echo "usage: $0 SEED_RUN_ID SEED_RUN_ATTEMPT ACTIONS_SEED_KEY CHAIN_ID [START_GENERATION]" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
benchmark_repo="boringcache/benchmark-obs-studio"
continuation_branch="obs-continuation-$chain_id"
restore_key="$actions_seed_key"

while IFS=$'\t' read -r generation parent_sha source_sha version _subject; do
  if [[ "$generation" == "generation" ]]; then
    continue
  fi
  if (( generation < start_generation )); then
    continue
  fi

  save_key="gha-xcode-continuation-${chain_id}-g${generation}-${source_sha:0:12}"
  run_url="$(
    gh workflow run obs-xcode-continuation.yml \
      --repo "$benchmark_repo" \
      --ref main \
      -f "generation=$generation" \
      -f "parent_sha=$parent_sha" \
      -f "source_sha=$source_sha" \
      -f "obs_version=$version" \
      -f "actions_restore_key=$restore_key" \
      -f "actions_save_key=$save_key" \
      -f "boringcache_seed_run_id=$seed_run_id" \
      -f "boringcache_seed_run_attempt=$seed_run_attempt" \
      -f "continuation_branch=$continuation_branch"
  )"
  run_id="${run_url##*/}"
  if [[ ! "$run_id" =~ ^[0-9]+$ ]]; then
    echo "Could not determine the dispatched workflow run from: $run_url" >&2
    exit 1
  fi

  echo "Generation $generation: $run_url"
  gh run watch "$run_id" --repo "$benchmark_repo" --interval 20 --exit-status
  restore_key="$save_key"
done < "$root/benchmark-continuation.tsv"
