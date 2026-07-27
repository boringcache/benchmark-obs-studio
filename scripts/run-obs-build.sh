#!/usr/bin/env bash
set -euo pipefail

surface="${1:-}"
log_path="${2:-}"
case "$surface" in
  ccache|xcode) ;;
  *)
    echo "usage: $0 ccache|xcode LOG_PATH" >&2
    exit 2
    ;;
esac
if [[ -z "$log_path" ]]; then
  echo "usage: $0 ccache|xcode LOG_PATH" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$(dirname "$log_path")"

if [[ "$surface" == "ccache" ]]; then
  cmake --build "$root/upstream/build_ubuntu" \
    --target obs-studio \
    --config RelWithDebInfo \
    --parallel 2>&1 | tee "$log_path"
  exit "${PIPESTATUS[0]}"
fi

derived_data_path="${BORINGCACHE_XCODE_DERIVED_DATA_PATH:-${OBS_BASELINE_DERIVED_DATA_PATH:-}}"
if [[ -z "$derived_data_path" ]]; then
  echo "No Xcode DerivedData path was configured." >&2
  exit 1
fi

(
  cd "$root/upstream/build_macos"
  xcodebuild \
    ONLY_ACTIVE_ARCH=NO \
    -project obs-studio.xcodeproj \
    -target obs-studio \
    -destination "generic/platform=macOS,name=Any Mac" \
    -configuration RelWithDebInfo \
    -parallelizeTargets \
    -hideShellScriptEnvironment \
    -derivedDataPath "$derived_data_path" \
    -showBuildTimingSummary \
    build 2>&1 | tee "$log_path"
  exit "${PIPESTATUS[0]}"
)
