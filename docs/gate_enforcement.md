# The gate as an invariant

The product's central guarantee is that it refuses biological claims until a
human supplies expert labels and reviewed regions. A review of the execution
paths found it enforced on one of four.

| Path | Entry point | Before | After |
| --- | --- | --- | --- |
| `run_pilot` | scripts, Studio pilot job | gated | gated |
| Studio plan runner | `POST /api/runs` | **UI only** | gated |
| `SpatialAgent` | batch, `POST /sessions/{id}/query` | readiness only | gated |
| `SpatialMindAgent` | non-Xenium data only | **none** | gated |

The Studio hole was demonstrable: `POST /api/runs` with `region_summary`
against a section reporting `blocked_missing_validation_inputs` returned `200`
and started the job. The UI declined to send such a request, so the guarantee
held for anyone clicking and not for anyone scripting.

`SpatialMindAgent` was worse. It never consulted the gate, it runs
`AlgorithmEngine` — a separate three-tool registry disjoint from the 30-tool
`ToolRegistry`, two of whose tools name cell types — and
`DataIngestionLayer.load` accepts a Xenium directory.

Its exposure is narrower than it first appears, and worth stating precisely
because the first three attempts at this paragraph all overstated it. **Both**
shipped entry points check the data type first: the CLI and `POST /runs` each
route a Xenium bundle to `run_pilot`. The orchestrator therefore receives only
non-Xenium data — CSV, manifest, H5AD — where the gate's six asset conditions
cannot be evaluated at all. `--replay-run-id` adds no route of its own, since
only the orchestrator writes the `source_path` that branch reads.

What remained was a library-level hole rather than an endpoint one.
`DataIngestionLayer.load` accepts a Xenium directory, so
`SpatialMindAgent().run(prompt, xenium_path)` was ungated for any caller that
reached past the entry points — a script, a notebook, a future surface. The fix
closes that and, for the non-Xenium case it normally sees, replaces silence with
a recorded `gate_not_evaluated` caveat.

## One decision function

`spatialmind/gatekeeper.py` holds `require_gate_open`, and every executor calls
it before running anything. It returns one of three outcomes, or raises:

| Outcome | Meaning |
| --- | --- |
| `not_required` | No gated tool in the plan. The descriptive lane stays runnable on an unreviewed section — that is the whole reason it exists. |
| `gate_not_evaluated` | Gated tools on data the gate cannot assess. Permitted, with a caveat the caller must record. |
| `validated_ready` | Gated tools, gate open. |
| `GateBlockedError` | Gated tools, gate evaluable, gate shut. |

### Why `gate_not_evaluated` exists rather than a refusal

The gate's six conditions are Xenium assets. Off a Xenium bundle it cannot be
evaluated at all, which is not the same as passing and must not be allowed to
look like passing. Refusing outright would instead make the gate assay-lock the
system: the legacy demo path and any future modality would be unusable for
reasons of format rather than of evidence.

So that case is permitted and carries a caveat — *"these results are not
gate-validated and must not be reported as though they were"* — which the agent
loop appends to its warnings and the orchestrator writes into provenance. The
system already works this way elsewhere: capability states and claim caveats
record what could not be established instead of hiding it.

### Unknown tools are gated, not waved through

`AlgorithmEngine`'s tools are not in the registry, so preconditions cannot
classify them. `cell_type_distribution` and `cell_type_colocalization` are named
explicitly as label-gated. An unrecognised tool is treated as gated: an
unrecognised name is not evidence of safety.

## Layering

`gatekeeper` imports `ingestion`, `tools`, `schemas` and `contracts` and nothing
else, so `agent`, `api`, `batch`, `pilot` and `app` can all reach it without a
cycle. `pilot_gate` moved here for that reason — it lived in `pilot.xenium`,
which imports `agent.runtime`, so any agent-layer caller would have closed a
loop. `spatialmind.pilot.pilot_gate` still resolves to the same function.

An import-linter contract pins this: `gatekeeper` may not import `agent`, `api`,
`app`, `batch`, `pilot`, `storage` or `viz`. If someone reaches upward, the
build fails rather than the layering silently rotting.

`app.planner` no longer keeps its own copy of the gated-tool rules; two copies
of a security-relevant predicate is how they drift.

## Tests that try to get past it

The suites had no negative cases — every eval case asserted that the right tool
*was* selected, none that a wrong one was refused. That is why a gate hole and a
scaffold-detection failure both survived a green suite. Five tests now attempt
the bypass:

- a gated tool while the gate is shut must return `409 gate_blocked`
- a descriptive plan on the same section must still be accepted
- a gated tool must be accepted once the gate opens
- a legacy tool outside the registry must still be classified as gated
- non-Xenium data must report `gate_not_evaluated`, never a pass

214 tests, 5/5 import contracts, 15/15 and 11/11 eval cases.
