# Public repository contents

Prepared on 2026-10-16. This document describes the source distribution;
it does not assert that a GitHub repository or release has been published.

Included: controller and executor source, the independent online-admission
extension, tests, configuration, experiment protocols and reports, formula
assets, environment records, aggregate results and measured policy inputs.

Excluded: model weights, virtual environments, per-request traces, generated
payloads, runtime logs, raw result directories, evidence archives, credentials,
local operating instructions and personal learning files. Exclusion does not
delete the local originals. Keep the repository and its sibling `work`
directory for complete local evidence verification.

## What a clean clone can verify

The V1 unit tests, 7B CPU control contracts, extension CPU/HTTP tests and
deterministic replays use synthetic inputs or the small checked-in policies.
They do not need a GPU, a model download, or the sibling evidence directory.
The CPU workflow runs these checks on Linux/Python 3.12. Passing it verifies
code contracts, not the published GPU performance measurements.

Full V1 and extension evidence audits require the archives listed in
[REPRODUCIBILITY.md](REPRODUCIBILITY.md). There is currently no public download
URL for them. Do not upload the entire `work` directory: it is an operational
workspace, not a reviewed release asset. Any future data release needs its own
content review and checksum manifest.

## Build a source snapshot

From the repository root:

```sh
python scripts/build_source_release.py ../slo-vllm-autotuner-source.zip
```

The command refuses to overwrite an existing ZIP. It includes both V1 and the
extension and records per-file SHA-256 hashes in `SOURCE_MANIFEST.json`.
This is a current source snapshot, not a reconstruction of a historical GPU
execution snapshot. Frozen historical evidence remains separate.

## Dependencies and licensing

This is a controller around [vLLM](https://github.com/vllm-project/vllm), not a
fork or a modification of its scheduler. Experiments use
[Qwen2.5 models](https://github.com/QwenLM/Qwen2.5); model weights are not bundled.
These upstream projects and all dependencies keep their own licenses.

No license for this repository has been selected yet. Publishing readable
source on GitHub is separate from granting an open-source license. Choose an
appropriate license before describing this repository as open source; do not
infer this project's license from vLLM's license.
