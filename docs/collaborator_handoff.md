# Collaborator Download and Review

Prepared 2026-10-02 for Katherine516/SpatialMind. Source code is versioned in Git;
large data and app binaries are distributed as GitHub release assets, not Git
blobs or Git LFS pointers.

## Current Native App

The [1.0.1 native macOS test prerelease](https://github.com/Katherine516/SpatialMind/releases/tag/studio-v1.0.1-native)
replaces the older Intel-only application download. Choose `arm64` for M-series
Macs or `x86_64` for Intel, on macOS 15 or newer. It includes DMG/ZIP installers,
`SHA256SUMS.txt` and a verification ZIP with both native manifests, dependency
inventories, runtime tests and synthetic example reports. No Python installation
or embedded dataset download is needed. These packages are ad-hoc signed, not
Apple-notarized. [Acceptance and installation details](macos_release_1_0_1.md).

The October 2 data snapshot below is a separate, older draft release. Access may
require maintainer permissions; publishing the native application does not make
that draft's data archives public.

## Release

[Download the collaboration snapshot](https://github.com/Katherine516/SpatialMind/releases/tag/collaboration-2026-10-02).

This is a research prerelease, not a biologically validated or production release.
The release tag identifies the exact source snapshot. The repository default
branch may differ until the accompanying pull request is merged.

| Asset | Contents |
| --- | --- |
| `SpatialMind-Studio-2026-10-02-macos-x86_64.zip` | September 30 tested Intel macOS app; no embedded datasets |
| `SpatialMind-data.tar.gz.part-*` | The full local `data/` snapshot, compressed and split in alphabetic order |
| `SpatialMind-data-inventory.json` | Relative data paths, sizes and owner redistribution attestation |
| `SpatialMind-glioblastoma-example.zip` | Sampled real-data HTML report, figures, tables and provenance |
| `SpatialMind-brain-specialist-review-packet.zip` | Frozen healthy-brain/GBM cohorts, candidate evidence and review worksheets |
| `SHA256SUMS` | Integrity checksums for all payload assets |
| `release_manifest.json` | Source commit, app limitations, asset sizes and checksums |

Each data part is below GitHub's 2 GiB release-asset limit. Download **every** part
before restoring the full data snapshot. Parts are not individually extractable.
Only macOS `.DS_Store` filesystem metadata is excluded from the data archive;
dataset files and existing review history are retained.

## Obtain the Exact Source

```bash
git clone --branch collaboration-2026-10-02 https://github.com/Katherine516/SpatialMind.git
```

Cloning this tag gives a detached, reproducible source snapshot. Create your own
working branch before making edits. Git cloning alone downloads only the tiny
tracked fixtures and provenance notes, not the full data or packaged application.

## Download and Verify All Assets

Install/authenticate the GitHub CLI, or download each asset from the release page.
Allow roughly 100 GB of free space for archives, extracted data and the app.

```bash
mkdir SpatialMind-release
gh release download collaboration-2026-10-02 \
  --repo Katherine516/SpatialMind --dir SpatialMind-release
cd SpatialMind-release
shasum -a 256 -c SHA256SUMS
```

Do not extract or use assets if any checksum fails. The complete checksum check
expects all payloads; downloading only the app or a report does not require
downloading the data, but compare that asset's SHA-256 with its listed value.

## Restore Data

From the download directory, with the cloned repository at `../SpatialMind`:

```bash
set -o pipefail
cat SpatialMind-data.tar.gz.part-* | tar -xzf - -C ../SpatialMind
```

Use a clean clone or back up existing `data/` first: extraction can replace local
files. The archive contains a `data/` top-level directory; do not extract it into
the existing `data/` directory itself. Preserve filenames with spaces. Do not
rename review candidates to approved truth or change frozen benchmark splits.

## App and Report

Extract the app ZIP in Finder. This bundle is Intel x86_64 only, ad-hoc signed and
**not Apple-notarized**. Native-window rendering and Apple Silicon compatibility
were not established by the headless smoke test. macOS may block downloaded
unnotarized applications. Use the source workflow or request a Developer ID-signed,
notarized distribution; do not disable security protections. No older DMG is
included as if it represented the current source.

Datasets are separate from the app. Select the restored data folder in Studio.
The app needs no API key for deterministic local analysis. Optional LLM services
require your own credentials; no credentials are distributed in this release.

For the example, extract `SpatialMind-glioblastoma-example.zip` and open
`glioblastoma_example/validated_xenium_pilot_report.html`. Keep its neighboring
assets. The legacy filename does not imply validated biology: the report correctly
shows `blocked_missing_validation_inputs`, with 1,500 sampled cells, 1,495 retained
and 9 expression clusters.

## Review Tasks and Validation Limits

Extract the specialist packet and start with its `REVIEW_INSTRUCTIONS.md`.
The brain single-cell specialist reviews identities and evidence; the
neuropathologist reviews anatomy, pathology and matched-image alignment. Each
healthy-brain/GBM cohort has 750 selected cells, not a whole-section review.
Review worksheets currently contain zero accepted specialist labels/regions.

Software verification for the source snapshot: 586/586 unit tests, six import
contracts, 16/16 legacy and 13/13 MVP routing cases. The packaged app passed 12/12
headless checks, including Scanpy clustering and Squidpy analysis on synthetic
data. These are not biological accuracy metrics. Genuine brain training, external
donor testing and reliability calibration still need reviewed truth and verified
donor evidence. See [the ordered review workflow](brain_review_execution.md).

## Sharing Attestation

On 2026-10-02, the repository owner explicitly confirmed that **all datasets are
cleared for public redistribution** after being informed that the GitHub repository
is public. The data inventory records this owner attestation; it is not an
independent license, consent or PHI audit. Original dataset provenance and terms
remain applicable. Do not infer specialist approval or verified donor independence
from public availability.

For later changes, keep raw datasets out of Git and publish a new checksum-bound
release snapshot. Returning reviews can contain reviewer identities or restricted
notes: agree on their sharing scope before uploading them to this public repository.
