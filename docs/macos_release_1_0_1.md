# SpatialMind Studio 1.0.1: Native macOS Acceptance

## Scope

This increment packages the current local agent snapshot as two native research
applications: Apple Silicon (`arm64`) and Intel (`x86_64`). It is not a
universal2 binary. Both target macOS 15 or newer and include their Python and
scientific libraries; collaborators do not need to install Python or requirements.
Raw datasets are not embedded in the application.

Build source: `9237f4033b4d22e5ee64d042f74d15a31900e287` on
`codex/macos-dual-architecture`. Documentation may be updated after that build.
[Native build run](https://github.com/Katherine516/SpatialMind/actions/runs/37874197461).
The existing primary working tree and older Intel package were preserved.

## Acceptance

[Published downloads and checksums](https://github.com/Katherine516/SpatialMind/releases/tag/studio-v1.0.1-native).
The verification ZIP was also downloaded locally and matched its published
SHA-256 (`6c6a21f14eb352266e4e30c854270a4062a1b32053c0c1793d2a01c4f13754aa`).

- Full local regression: **645/645 tests passed**, 302.327 seconds, Python 3.9.
- End-to-end source acceptance: **13/13 checks passed** after the HTML delivery fix.
- Apple Silicon: **13/13 packaged checks passed**; visible Cocoa/WKWebView probe passed.
- Intel: **13/13 packaged checks passed**; visible Cocoa/WKWebView probe passed.
- Publication guards: **9/9 focused tests passed** after the full 645-test run.

| Native Package | Bundled Interpreter | App Size (MiB) | Mach-O Files Audited | Incompatible / Unreadable |
| --- | --- | ---: | ---: | --- |
| Apple Silicon | CPython 3.11.9 | 872.5 | 614 | 0 / 0 |
| Intel | CPython 3.11.9 | 1001.8 | 618 | 0 / 0 |

The cached native interpreter is not the newest CPython security-patch runtime.
Upgrade and revalidate that runtime before production distribution; the current
release is explicitly a research test package, not a security certification.

CI uses native Python 3.11 and separate constrained application environments.
Each release manifest records the actual interpreter version, source commit,
architecture, library audit, signing status and runtime test results. The complete
installed package inventory is archived, not inferred from the top-level requirements.

The synthetic Xenium fixture contains 300 cells and 40 measured features.
Packaged checks cover deferred folder scanning, UI serving, dataset discovery,
cell indexing, review-gate refusal/acceptance, scaffold refusal, dependency
planning, strict real Scanpy clustering and Squidpy Moran statistics, figures,
HTML delivery and PDF/DOCX/XLSX exports. The native test checks the visible window,
WKWebView DOM and native bridge, plus directory-only NSOpenPanel construction.
It does not pretend to exercise interactive folder consent.

The initial ARM run found an existing report endpoint defect: the API selected
Markdown before HTML from a result-path dictionary. The endpoint now selects
only an existing `.html` file and returns 404 when none exists. Two regression
tests cover Markdown-first ordering and missing HTML. Failed initial builds were
not released. The new test harness also supports both script and module imports.

## Installation

Choose `arm64` for an Apple M-series Mac or `x86_64` for an Intel Mac.
Use one DMG, copy `SpatialMind Studio.app` to Applications and open it. The ZIP
is an alternative archive of the same architecture's application. Keep the two
architectures separate; they use the same application name.

Verify a downloaded file against the published SHA-256 inventory before use:

```bash
shasum -a 256 SpatialMind-Studio-1.0.1-macos-arm64.dmg
```

These are **ad-hoc signed test packages**, not Apple-notarized distribution
releases. Gatekeeper can block a downloaded copy. Only consider a per-app
exception after verifying its source and integrity; never disable Gatekeeper
globally. See [Apple's guidance](https://support.apple.com/en-us/102445).
Developer ID signing/notarization is implemented but remains untested without
the owner's Apple credentials. Required Actions secrets and commands are in
[the packaging guide](spatialmind_studio.md#signing-and-notarization).

The native build run and final checksum/publication run both succeeded. GitHub
blocked release creation by the Actions token for the workflow-changing source
commit. The maintainer created the exact source tag and empty prerelease draft;
CI verified both artifacts and uploaded without overwrite, then the maintainer
published the completed draft. No personal credentials were stored in CI.

## Remaining Acceptance

1. Configure a Developer ID certificate and Apple notarization credentials;
   rebuild, verify the notarization ticket and test a quarantined download.
2. Test folder selection/consent, denied access, external drives, layout and
   repeated launch/close behavior on collaborator devices.
3. Run representative large Xenium bundles on each target Mac and record memory,
   latency and export sizes. A 300-cell fixture is not a scaling benchmark.
4. Maintain security/dependency review of the pinned scientific runtime. Pins
   make builds reproducible; they are not a claim of zero vulnerabilities.
5. Complete real specialist labels, anatomical regions and independent donor
   testing. Packaging success does not validate cell annotations or biological
   claims. No human review files were fabricated or training gates relaxed.
