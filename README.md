# benchmark-obs-studio

Reproducible compiler-cache proof for
[`obsproject/obs-studio`](https://github.com/obsproject/obs-studio). It compares
OBS Studio's existing GitHub Actions cache strategy with BoringCache on both of
the native compilation surfaces that OBS already operates:

- ccache on Ubuntu 24.04
- Xcode compilation caching on macOS 26 with Xcode 26.5

## Why OBS Studio

OBS is a large, active C/C++ application whose own CI already carries the
operational cost this benchmark is meant to test. Its Ubuntu workflow restores
and saves `.ccache`; its macOS workflow restores and saves Xcode's
`CompilationCache.noindex`. The upstream `ubuntu-ci` CMake preset enables
ccache, while `macos-ci` enables Xcode compilation caching and supplies the CAS
path. This is existing production pain, not a cache added for the benchmark.

## The question

For a normal adjacent OBS commit on fresh runners, can BoringCache's native
remote adapters beat downloading and unpacking the previous compiler-cache
directory?

The proof records cache setup or restore time, build time, and their sum. It
also requires native evidence before accepting a BoringCache result:

- ccache must report remote writes for the base build and remote hits for the
  rolling build, with no remote errors or timeouts;
- Xcode must report published actions and objects for the base build, then
  action hits plus fetched objects and bytes with zero publications in the
  restore-only rolling build.

## Pinned rolling pair

[`benchmark-source.env`](benchmark-source.env) pins this parent/child pair:

- base: `6750a6e9f5248bbefbc67adb49fb819e6611e284`
- head: `f730063da39f2e6338629f526acb99c8d574ffa1` (`32.2.0-rc2`)
- change: a real adjustment to the Add Source frontend, including
  `frontend/dialogs/OBSBasicSourceSelect.cpp`

`prepare-source.sh` verifies the parent relationship before either build and
updates OBS's recursive submodules at the selected commit.
`benchmark-source.env` also pins the semantic OBS build version so the
untagged parent and tagged child use the same valid CMake version metadata.

## Comparison shape

Each strategy runs four fresh-runner jobs:

1. seed the ccache surface from the base commit;
2. build the rolling commit against that ccache state;
3. seed the Xcode compilation cache from the base commit;
4. build the rolling commit against that Xcode CAS state.

The Actions Cache lane mirrors OBS's cache directories. The BoringCache lane
uses canonical `mode: ccache` and `mode: xcode` Action entrypoints with
`setup: none`; cache identity lives in [`.boringcache.toml`](.boringcache.toml).
The rolling BoringCache jobs receive only a restore token and use
`trust-policy: restore`.

Dependency installation, CEF/framework downloads, and CMake generation happen
before the build timer. Both strategies compile the upstream `obs-studio`
target. DerivedData is fresh on every Xcode runner; only the compilation CAS is
reused.

## Release boundary

The benchmark templates are intentionally inactive until a public
`boringcache/one` `v1.15.0` distribution commit contains both adapters.
Substituting a mutable or knowingly incompatible ref would make the proof
invalid.

After that release, activate the workflows with its reviewed distribution SHA
and stable version:

```console
./scripts/activate-workflows.sh 0123456789abcdef0123456789abcdef01234567 v1.15.0
```

The activation script checks the public Action metadata, requires a
40-character SHA, verifies that the Action's default CLI version matches the
stable Action version, and renders the three files in `.github/workflows/`.
Every accepted phase artifact records those exact Action and CLI refs plus a
fail-closed cold/rolling classification; mixed or invalid cohorts cannot render
a comparison. Run the benchmark cache-interface contract check before
publishing this repository.

## Local checks

```console
python3 -m unittest discover -s test -v
shellcheck scripts/*.sh
```

The full OBS builds are GitHub-only because they install the same system and
Homebrew dependencies as OBS's hosted CI.
