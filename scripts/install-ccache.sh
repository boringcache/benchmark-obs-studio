#!/usr/bin/env bash
set -euo pipefail

ccache_version=4.14
ccache_archive="ccache-${ccache_version}-linux-x86_64-glibc.tar.gz"
ccache_sha256=c64760b0b85ba86068f4cd162dc42e2dc39c6f46b0cb8c1990dfccbec7a1fed0
ccache_url="https://github.com/ccache/ccache/releases/download/v${ccache_version}/${ccache_archive}"

storage_version=0.9
storage_archive="ccache-storage-http-go-${storage_version}-linux-amd64.tar.gz"
storage_sha256=875dbf6d575d06e4c4492f1ba639beb68530bc23382031a6bacc767cded9f463
storage_url="https://github.com/ccache/ccache-storage-http-go/releases/download/v${storage_version}/${storage_archive}"

install_root="${RUNNER_TEMP:?RUNNER_TEMP is required}/ccache-${ccache_version}"
temp_root="$(mktemp -d "${RUNNER_TEMP}/ccache-download.XXXXXX")"
trap 'rm -rf "$temp_root"' EXIT

curl --fail --silent --show-error --location "$ccache_url" --output "$temp_root/$ccache_archive"
echo "$ccache_sha256  $temp_root/$ccache_archive" | sha256sum --check --status
tar -xzf "$temp_root/$ccache_archive" -C "$temp_root"

curl --fail --silent --show-error --location "$storage_url" --output "$temp_root/$storage_archive"
echo "$storage_sha256  $temp_root/$storage_archive" | sha256sum --check --status
tar -xzf "$temp_root/$storage_archive" -C "$temp_root"

mkdir -p "$install_root/bin"
install -m 0755 "$temp_root/ccache-${ccache_version}-linux-x86_64-glibc/ccache" "$install_root/bin/ccache"
install -m 0755 "$temp_root/ccache-storage-http-go-${storage_version}-linux-amd64/ccache-storage-http" "$install_root/bin/ccache-storage-http"
echo "$install_root/bin" >> "${GITHUB_PATH:?GITHUB_PATH is required}"

"$install_root/bin/ccache" --version | head -1
if [[ "$("$install_root/bin/ccache-storage-http" --version 2>&1)" != *"Version: ${storage_version}"* ]]; then
  echo "expected ccache-storage-http ${storage_version}" >&2
  exit 1
fi
