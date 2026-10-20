# Project Cleanup Review: 2026-10-20

## Scope and Decision Rule

This is a dependency and file-retention review, not a new biological validation
or an assertion that every retained file will be useful forever. Future use cannot
be proved from filenames. Remove only positively identified obsolete code and
regenerable build/cache artifacts; preserve uncertain research and release records.

Reviewed the tracked-file inventory, untracked development files, top-level storage
usage, entry points, build configuration, CI, source imports and relevant documentation.
Parsed all 210 first-party Python files before cleanup and resolved relative import
references. No nonempty Python files were byte-identical. Scientific data files and
release archives were inventoried by directory/size, not exhaustively decoded or
validated. Git internals and the installed environment were not pruned.

## Removed

The [exact file inventory](cleanup_inventory_20261020.md) lists each removed path,
its byte size, pre-removal SHA256 and reason. It covers 239 files totaling
252,507,537 logical bytes (240.81 MiB):

- `spatialmind/algorithms.py`: retired, unreferenced v1 analysis engine.
- `build/SpatialMindStudio/`: reproducible PyInstaller intermediates, including
  TOCs, archives, analysis listings, collected bytecode and the intermediate binary.
- `.import_linter_cache/`: regenerable import-graph cache.
- First-party `__pycache__/*.pyc` with matching source files.
- Two orphan CPython caches for removed `algorithms` and storage `identity`
  modules. These are interpreter cache entries, not standalone bytecode modules.
- Finder `.DS_Store` files outside protected datasets, reports and application bundles.

Removed the obsolete module export/layer entry and corrected current architecture descriptions.
Generated-file deletion used an exact manifest with hash, size, symlink and tracked-
file checks. No broad recursive deletion of data, outputs or installed dependencies
was performed. Empty cache/build directories were pruned after file removal.

## Source Compatibility

The old `AlgorithmEngine` has no static importers, and repository text/config
search found no dynamic import reference. `SpatialMindAgent` already converts old
intent names to canonical annotation, neighborhood enrichment and gene-overlay
tools, then calls `agent.runtime.execute_tool_step`.

External code that directly imports `spatialmind.algorithms.AlgorithmEngine` must
migrate to the canonical tools and shared runtime. Removing this unused repository
module is an intentional retirement, not a promise of compatibility with unknown
external scripts. Git retains its historical source.

Keep `spatialmind/agent_loop.py`, `spatialmind/visualization.py`,
`spatialmind/app/planner.py` and the legacy intent parser. These are compatibility
surfaces, and some have active callers/tests. Keep `schemas.py`: its data classes
and expression/control-feature helpers are active shared contracts.

## Retained and Why

| Paths | Decision |
| --- | --- |
| `data/`, ontology terms, provenance notes and test fixtures | Research inputs, review material, reference identity and regression evidence. |
| `outputs/`, `.spatialmind/`, SQLite databases and knowledge workspaces | Run history, hash-linked artifacts, training records, review packets and user content. Deleting apparently old results can break replay or citations. |
| `outputs/github_release_20261002/` (about 41 GB) | Release archive parts and verification records. Current `data/` is only about 7.2 GB; these archives are not established duplicates and may contain otherwise absent data. No remote availability/recoverability check was performed. |
| `dist/` (about 2.5 GB) | Packaged deliverables and their companion collection. No application resources or signatures were modified. |
| `.venv/`, `spatialmind.egg-info/` | Working environment and installed distribution metadata. The latter can participate in package/version discovery. |
| `packaging/`, icon assets, build/release scripts, CI and Docker configuration | Rebuilding and distributing Intel/Apple Silicon apps and optional service workflows. Build intermediates are distinct from these inputs. |
| Requirements files and `environment.yml` | Different core, desktop, developer and isolated deep-learning environment roles; not interchangeable duplicates. |
| `eval/`, `tests/`, historic evaluation documents and plans | Regression coverage, scientific caveats, project history and unfinished acceptance criteria. |
| Registered scaffold tools | Capability/refusal tests intentionally check that 18 unavailable tools are excluded from the 12 plannable tools. Their presence is part of the capability contract, not evidence that they can execute. |
| `spatialmind/batch/celery_app.py`, `spatialmind/cli.py` | Entrypoints can be loaded by command/module name without static Python importers. |
| `spatialmind/config.py` | Small environment/settings compatibility surface; absence of internal imports alone is insufficient evidence to retire it here. |
| Existing modified/untracked source files | Ongoing user/Claude development; preserved rather than treated as clutter. |

## Verification

- Both CLI routing evaluations passed: legacy 16/16 and MVP 13/13, including
  scaffold exclusion, gate coverage and precondition invariants. These are
  routing/contract checks, not biological-accuracy measurements.
- All six architecture import contracts passed without a cache (137 modules,
  327 dependencies). The retired module was removed from the layer declaration.
- All remaining first-party Python files parsed, and documentation counts matched
  discovery (718 tests, 30 registered tools, 12 plannable tools).
- The deletion manifest read-back found none of its 239 paths still present.
  Protected data, output, environment, state and packaged-app roots remain.
- Full regression: 718 tests ran in 252.103 seconds, with 717 passing and one
  skipped. Existing sparse-efficiency, dependency-deprecation and test-resource
  warnings were non-fatal. No new native package build or biological validation
  was performed.
- `git diff --check` passed. The only tracked file deletion is
  `spatialmind/algorithms.py`; unrelated pre-existing edits remain in place.

Regression logs and evaluation JSON are retained in
`outputs/project_cleanup_20261020/`. Verification ran with bytecode writes
disabled and the import-linter cache disabled so it did not immediately recreate
the deleted caches.

## Future Retention Work

The largest possible saving requires a separate archive-retention decision, not
more source deletion. First verify every release archive part against its manifest
and an accessible independent copy; establish whether missing local datasets can
be restored; then decide how many local copies to retain. For analysis outputs,
inventory references from run databases, reports and knowledge citations before
archiving anything. Do not delete reviewed truth, benchmark splits or model provenance
because a newer output folder exists.
