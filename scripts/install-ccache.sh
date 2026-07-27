#!/usr/bin/env bash
set -euo pipefail

version=4.13.6
archive="ccache-${version}-linux-x86_64-glibc.tar.gz"
expected_sha256=567b1b648411819590f918f045218c92da14418bdec3b30db94a3b4f5d77cf13
url="https://github.com/ccache/ccache/releases/download/v${version}/${archive}"
install_root="${RUNNER_TEMP:?RUNNER_TEMP is required}/ccache-${version}"
temp_root="$(mktemp -d "${RUNNER_TEMP}/ccache-download.XXXXXX")"
trap 'rm -rf "$temp_root"' EXIT

curl --fail --silent --show-error --location "$url" --output "$temp_root/$archive"
echo "$expected_sha256  $temp_root/$archive" | sha256sum --check --status
tar -xzf "$temp_root/$archive" -C "$temp_root"
mkdir -p "$install_root/bin"
install -m 0755 "$temp_root/ccache-${version}-linux-x86_64-glibc/ccache" "$install_root/bin/ccache"
echo "$install_root/bin" >> "${GITHUB_PATH:?GITHUB_PATH is required}"

"$install_root/bin/ccache" --version | head -1
