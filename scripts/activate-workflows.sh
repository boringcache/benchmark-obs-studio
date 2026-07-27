#!/usr/bin/env bash
set -euo pipefail

action_sha="${1:-}"
action_version="${2:-}"
if [[ ! "$action_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 BORINGCACHE_ONE_40_CHARACTER_SHA vX.Y.Z" >&2
  exit 2
fi
if [[ ! "$action_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 BORINGCACHE_ONE_40_CHARACTER_SHA vX.Y.Z" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action_url="https://raw.githubusercontent.com/boringcache/one/${action_sha}/action.yml"
action_yaml="$(curl --fail --silent --show-error --location "$action_url")"

if ! grep -q '^  ccache-version:' <<<"$action_yaml"; then
  echo "boringcache/one@$action_sha does not expose the ccache adapter." >&2
  exit 1
fi
if ! grep -q 'ccache.*xcode\|xcode.*ccache' <<<"$action_yaml"; then
  echo "boringcache/one@$action_sha does not advertise both ccache and xcode modes." >&2
  exit 1
fi
cli_version="$(sed -n -E "/^  cli-version:/,/^[^[:space:]]/ s/^[[:space:]]*default:[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" <<<"$action_yaml" | head -1)"
if [[ "$cli_version" != "$action_version" ]]; then
  echo "boringcache/one@$action_sha defaults to CLI ${cli_version:-<missing>}, expected aligned release $action_version." >&2
  exit 1
fi

mkdir -p "$root/.github/workflows"
for template in "$root"/workflow-templates/*.yml; do
  output="$root/.github/workflows/$(basename "$template")"
  sed \
    -e "s/__BORINGCACHE_ONE_SHA__/$action_sha/g" \
    -e "s/__BORINGCACHE_ONE_VERSION__/$action_version/g" \
    -e "s/__BORINGCACHE_CLI_VERSION__/$cli_version/g" \
    "$template" > "$output"
done

if grep -R -n -E '__BORINGCACHE_(ONE_SHA|ONE_VERSION|CLI_VERSION)__|boringcache/one@(v[0-9]+|main|master)' "$root/.github/workflows"; then
  echo "Generated workflows contain an unresolved or mutable BoringCache Action ref." >&2
  exit 1
fi

echo "Activated benchmark workflows with boringcache/one@$action_sha ($action_version, CLI $cli_version)"
