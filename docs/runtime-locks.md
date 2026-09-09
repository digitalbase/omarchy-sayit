# Runtime lock review

The supported runtime is Kokoro 0.9.4 on Linux x86-64 CPU with CPython 3.11.16.
Other engines, CUDA, Japanese and Chinese are disabled. The historical adapters
are available in Git history, but enabling them requires equivalent source locks
and offline validation, including tokenizers, codecs and language dictionaries.

## Model provenance

`hexgrad/Kokoro-82M` is fixed to commit
`f3ff3571791e39611d31c381e3a41a3af07b4987`. The manifest's weight and voice SHA-256
values were obtained from the Hugging Face LFS metadata at that commit; the
config digest was computed from the file fetched at that commit. Local cached
artifacts were checked against these values. The locked Kokoro implementation
loads weight/voice tensors with PyTorch `weights_only=True`.

The downloader has no model-library imports. It requests exact listed filenames
from the immutable revision, verifies bytes before publishing them and never
runs a model. The worker verifies the complete artifact set before importing
PyTorch/Kokoro. Unknown artifacts, unsafe paths and undeclared voice files are
rejected. Custom models must supply the same commit/hash fields, validated both
at registration and before download/load. These fields identify content, not
authorship or trustworthiness.

### Download size limits

The downloader enforces fixed maximum sizes for both built-in and custom models:

| Artifact | Maximum bytes | Pinned upstream bytes |
| --- | ---: | ---: |
| `config.json` | 65,536 | 2,351 |
| `kokoro-v1_0.pth` | 367,001,600 | 327,212,226 |
| Each `voices/*.pt` | 1,048,576 | 523,420 to 523,430 |

The upstream sizes were checked against Hugging Face tree metadata at the pinned
commit above on 2026-09-09. The limits allow headroom while bounding each download;
model metadata cannot raise them. Larger artifacts require a reviewed code change.
An oversized `Content-Length` is rejected before reading the body. Streaming also
counts bytes regardless of the header, reading at most one byte beyond the limit
to detect overflow and rejecting that chunk before writing it. Any failure removes
the temporary file, preserves the previous target, and leaves no ready marker.
The SHA-256 check remains required before publishing an artifact.

## Dependency and bootstrap provenance

- `kokoro.in` records the selected top-level versions and direct CPU PyTorch and
  spaCy model wheel URLs. `kokoro-linux-x86_64.txt` contains their full resolved
  dependency closure and SHA-256 distribution hashes from uv 0.12.10.
- Resolution used the official PyPI index plus the two explicit upstream wheel
  URLs. The closure and URLs were inspected: no Git dependencies, editable
  sources or runtime source builds are allowed. Some packages publish hashes
  for several distributions; installation still permits wheels only.
- `bootstrap.txt` fixes uv 0.12.10 and hashes its distributions. Bootstrap uses
  the host Python's bundled venv/pip, hash-required wheel-only installation and
  no dependency resolution. System Python and pip are host prerequisites.
- `python-downloads.json` is the single Linux x86-64 CPython 3.11.16 entry from
  uv 0.12.10's `crates/uv-python/download-metadata.json`. It fixes the
  python-build-standalone release `20260901`, full archive URL and SHA-256.
  Setup gives uv this local metadata file; it cannot select a newer Python
  release. The archive is reinstalled with checksum validation during setup.
- Setup runs `uv pip sync --require-hashes --only-binary :all: --reinstall`,
  disables uv config/cache use, strips inherited package-manager overrides, and
  uses the explicit Python executable with automatic Python downloads disabled.
  A lock digest isolates the resulting environment from legacy installations.

The download guard rejects Python socket connects/DNS and subprocess execution
during inference, except the exact `/sbin/ldconfig -p` system-library lookup used
by ctypes. This is defense against implicit library downloads, not a security
sandbox for malicious native code. Hashes do not replace code review or timely
dependency updates.

## Building the project

Normal installation runs the source checkout and performs no project build.
For an sdist/wheel, run `scripts/build.sh`. It installs `build.txt` with exact
hashes and wheels only, then invokes `build --no-isolation`, preventing a second
unlocked build-dependency resolution. The pyproject build backend is pinned to
the same setuptools version. The locks are included as package data.

## Updating a lock

Use the pinned uv to compile `sayit/locks/kokoro.in` with
`--python-version 3.11 --python-platform x86_64-manylinux_2_28 --generate-hashes
--only-binary :all:`. Review the complete diff and upstream artifacts before
committing. Do not update model hashes automatically after a verification
failure. Re-run unit tests, a clean hash-required install, and offline English
and Spanish synthesis before submitting the new exact commit.
