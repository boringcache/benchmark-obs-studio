#!/usr/bin/env bash
set -euo pipefail

version=4.14
archive="ccache-${version}-linux-x86_64-glibc.tar.gz"
expected_sha256=c64760b0b85ba86068f4cd162dc42e2dc39c6f46b0cb8c1990dfccbec7a1fed0
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
