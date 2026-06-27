# SpatialMind Layer Plan Review

Reviewed plan: `/Users/dongli/Desktop/Spatial_omics/SpatialMind/spatialmind layer plan.html`

## Executive Assessment

The layer plan is scientifically strong and architecturally sound. Its best ideas are not only the six-layer decomposition, but the hard safety boundaries around them:

- shared typed contracts between layers,
- modality-aware ingestion/readiness before analysis,
- typed tool failures instead of empty or misleading outputs,
- refusal when the requested workflow is not scientifically supported,
- claim grounding before interpretation reaches the user,
- method citations and provenance suitable for manuscript/reviewer scrutiny,
- import-boundary checks so the architecture does not decay silently.

The current SpatialMind codebase already implements a useful vertical slice: ingestion, wrappers, deterministic agent planning, visualization, memory, storage, eval, and validated Scanpy/Squidpy execution. The main gap is that several boundary contracts still live in `spatialmind.schemas` and some layer responsibilities are coupled for convenience. This pass begins the planned migration without breaking the working agent.

## What Already Matched The Plan

- Six practical layer directories already exist: `ingestion`, `tools`, `agent`, `viz`, `memory`, `storage`.
- H5AD and Xenium ingestion are implemented, including real Xenium `cell_feature_matrix.h5` loading.
- The default registry exposes 22 tools, including the P0 workflow set and v2 extensions.
- Real Scanpy/Squidpy wrappers exist for differential expression, clustering, variable genes, and neighborhood enrichment.
- Reports, QC dashboards, static/interactive spatial visualization, memory, local storage, and provenance already exist in prototype form.
- Eval harness has 15 cases and currently passes with mean score 1.0000.

## Important Differences From The Plan

- The plan recommends exact older pins such as Scanpy 1.9.8 and Squidpy 1.4.2. The validated local stack is newer and working: Scanpy 1.10.3 and Squidpy 1.6.1. I kept the validated stack and added a compatibility version gate rather than downgrading.
- The plan asks for pydantic v2 contracts everywhere. This pass adds dependency-light dataclass contracts first, because the repo intentionally keeps base tests runnable without the full stack. A future migration can switch the contract internals to pydantic once the public shape stabilizes.
- The plan sketches PostgreSQL/S3/Redis/Chroma production services. The current agent remains local-file first, with Docker Compose service placeholders. That is appropriate while the scientific contracts are still evolving.

## Implemented In This Pass

- Added `spatialmind/contracts/` with shared contract modules:
  - `artifacts.py`
  - `spatial_data.py`
  - `tool_io.py`
  - `plan.py`
  - `claims.py`
  - `response.py`
  - `reports.py`
  - `memory.py`
  - `citations.py`
  - `errors.py`
- Added modality-aware readiness scoring in `spatialmind/ingestion/readiness.py`.
- Wired the deterministic agent loop to return a structured `NoAnalysisResponse` when a requested workflow is blocked by readiness.
- Added `ResourceProfile` and `MethodCitation` metadata to every tool registry entry.
- Updated the structured report builder so a Methods section can be generated from method citations.
- Added `spatialmind/versioning.py` and `make check-versions` to validate the runtime stack.
- Added `.importlinter` and `make import-lint` for enforceable boundary checks.
- Added `import-linter` to `requirements.txt` and `pyproject.toml` dev dependencies.
- Added tests for readiness, structured refusal, contracts, claim grounding, and citation metadata.

## Validation

- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m compileall spatialmind tests` passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m unittest discover -s tests -p 'test_*.py'` passed 22/22 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/spatialmind_pycache python3 -m eval.runner` passed 15/15 eval cases with mean score 1.0000.
- `.venv/bin/python -m spatialmind.versioning` passed with the installed Scanpy/Squidpy environment.
- `.venv/bin/lint-imports` passed: 3 contracts kept, 0 broken.

## Recommended Next Build Steps

1. Migrate `spatialmind.schemas` objects gradually into `spatialmind.contracts`, keeping aliases until all callers are updated.
2. Split `spatialmind/tools/implementations.py` into one module per P0 tool, preserving the registry interface.
3. Add a formal `agent/grounding.py` that extracts `BiologicalClaim` objects from interpretations and applies the evidence rules.
4. Add planner mode gating (`safe`, `standard`, `expert`) and expose it through CLI/API.
5. Extend eval with the plan's adversarial cases: missing labels, unsupported modality, no QC approval, insufficient spots, invalid claim, privacy guard, replay reproducibility, and unsupported fusion.
6. Add production storage adapters behind the existing local `StorageLayer`: PostgreSQL metadata and S3/MinIO object storage.
7. Add benchmark-backed tests for CellTypist, Cell2location, inferCNVpy, decoupler, and SpatialDE/SpatialDE2 before treating those wrappers as production methods.

## Current Update

After the v7 MVP implementation, the most important layer-plan gap is not the existence of layer boundaries; those now exist and are checked. The priority is improving the scientific fidelity inside the boundaries:

- annotation confidence and evidence tracking,
- real reference label transfer,
- real motif/TF activity backends,
- larger adversarial eval coverage,
- supervised query-plan-result training records.

The latest Xenium breast run confirms the local storage, visualization, reporting, and provenance path works end to end on real data.
