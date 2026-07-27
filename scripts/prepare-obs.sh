#!/usr/bin/env bash
set -euo pipefail

surface="${1:-}"
strategy="${2:-}"
case "$surface:$strategy" in
  ccache:actions-cache|ccache:boringcache|xcode:actions-cache|xcode:boringcache) ;;
  *)
    echo "usage: $0 ccache|xcode actions-cache|boringcache" >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The pinned source pair intentionally uses an untagged parent commit. OBS's
# version helper otherwise falls back to the abbreviated SHA, which is not a
# valid CMake project version.
# shellcheck disable=SC1091
source "$root/benchmark-source.env"
upstream="$root/upstream"

if [[ ! "${OBS_VERSION_OVERRIDE:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(rc|beta)[0-9]+)?$ ]]; then
  echo "OBS_VERSION_OVERRIDE must be a pinned OBS semantic version." >&2
  exit 1
fi

if [[ "$surface" == "ccache" ]]; then
  if [[ "$(uname -s)" != "Linux" ]]; then
    echo "The ccache surface requires Linux." >&2
    exit 1
  fi

  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends zsh

  (
    cd "$upstream"
    CI=1 zsh --no-rcs --errexit --pipefail -c '
      setopt NO_UNSET ERR_RETURN
      project_root=$PWD
      target=ubuntu-x86_64
      host_os=ubuntu
      SCRIPT_HOME=$PWD/.github/scripts
      fpath=($SCRIPT_HOME/utils.zsh $fpath)
      autoload -Uz check_ubuntu setup_ubuntu
      check_ubuntu
      setup_ubuntu
    '

    cef_root="$(find .deps -mindepth 1 -maxdepth 1 -type d -name 'cef_binary_*_linux_x86_64' -print -quit)"
    if [[ -z "$cef_root" ]]; then
      echo "OBS dependency setup did not produce the Linux CEF directory." >&2
      exit 1
    fi

    cmake -S . --preset ubuntu-ci \
      -DOBS_VERSION_OVERRIDE:STRING="$OBS_VERSION_OVERRIDE" \
      -DENABLE_BROWSER:BOOL=ON \
      -DCEF_ROOT_DIR:PATH="$PWD/$cef_root" \
      -DCMAKE_C_COMPILER_LAUNCHER:FILEPATH=ccache \
      -DCMAKE_CXX_COMPILER_LAUNCHER:FILEPATH=ccache
  )
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The Xcode surface requires macOS." >&2
  exit 1
fi

: "${OBS_XCODE_PATH:?OBS_XCODE_PATH must be exported from benchmark-source.env}"
sudo xcode-select --switch "$OBS_XCODE_PATH"

(
  cd "$upstream"
  brew bundle --file .github/scripts/.Brewfile

  cmake_args=(
    -S .
    --preset macos
    -DOBS_VERSION_OVERRIDE:STRING="$OBS_VERSION_OVERRIDE"
    -DCMAKE_OSX_ARCHITECTURES:STRING=arm64
    -DCMAKE_COMPILE_WARNING_AS_ERROR:BOOL=ON
  )

  if [[ "$strategy" == "actions-cache" ]]; then
    : "${XCODE_CAS_PATH:?XCODE_CAS_PATH is required for the Actions Cache baseline}"
    mkdir -p "$XCODE_CAS_PATH"
    cmake_args+=(
      -DCMAKE_XCODE_ATTRIBUTE_COMPILATION_CACHE_ENABLE_CACHING:STRING=YES
      -DCMAKE_XCODE_ATTRIBUTE_COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS:STRING=YES
      -DCMAKE_XCODE_ATTRIBUTE_COMPILATION_CACHE_CAS_PATH:PATH="$XCODE_CAS_PATH"
    )
  else
    : "${XCODE_XCCONFIG_FILE:?The BoringCache Xcode adapter did not export XCODE_XCCONFIG_FILE}"
    : "${BORINGCACHE_XCODE_DERIVED_DATA_PATH:?The BoringCache Xcode adapter did not export a DerivedData path}"
  fi

  CODESIGN_IDENT=- CODESIGN_TEAM='' PROVISIONING_PROFILE='' cmake "${cmake_args[@]}"
)
