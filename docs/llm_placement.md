# Where the LLM goes, and how little it should do

The Studio ships with no LLM in it. `spatialmind/llm.py` has provider adapters
for OpenAI and Anthropic, `registry.to_anthropic_tools()` emits tool schemas
with scaffolds filtered out, and an eval invariant holds that surface honest —
*12 tools offered to a model, 0 of them known scaffolds*. All of it is wired to
`spatialmind/cli.py` and `spatialmind/api/app.py`, neither of which is the
product. The harness for a model exists and is unused.

This is what should go in it, and — more importantly — what should not.

## The rule

> The LLM picks the destination. The DAG computes the route. The gate decides
> whether you are allowed to describe where you arrived.

Everything below is that sentence with the reasons attached.

## Why the shape of the workflow decides the answer

Strip the stages away and the system is one idea: compute everything the data
supports, and withhold the right to *name* any of it until a human supplies the
judgement the data cannot.

The two lanes are the same computation with different permission to speak.
`qc_and_cluster` runs identically on both sides of the gate; what changes is
what the output may be called. Descriptive: *"every group below is data-derived
— a Leiden cluster, not a cell type."* Validated: *"reviewed cell labels were
applied, so groups below are named cell types."* Same Leiden, same graph, same
numbers, same seed. The gate governs vocabulary, not mathematics.

That tells you where a language model can help and where it cannot. It can help
a person say what they want and consider what a cluster might be. It cannot be
the thing that decides a claim is true, because the entire product is the
refusal to let fluency stand in for evidence — and fluency is what a language
model produces most cheaply.

## The plan is a DAG, and the edges are data

`order_plan` in `spatialmind/app/planner.py` is a topological sort, but not over
tool names. `TOOL_REQUIRES` declares what each tool *consumes*,
`MVP_TOOL_OUTPUTS` declares what it *produces*, and the resolver maps each
required key back to its producer and recurses. The graph is bipartite over
artifacts and collapses to a tool ordering:

```
marker_detection          ->  qc_and_cluster -> annotation -> marker_detection
region_summary            ->  qc_and_cluster -> annotation -> region_summary
all three goals at once   ->  qc_and_cluster -> annotation -> marker_detection
                              -> region_summary -> cell_neighborhood_enrichment
```

Three goals, one ordering, shared work done once. Cycles terminate on the `seen`
path tuple rather than recursing.

Two properties of this graph matter for the question at hand.

**Some nodes are roots.** `spatial_variable_genes` requires `normalized_counts`
and `spatial_coords`, which are dataset inputs rather than tool outputs, so it
plans as a single step with nothing upstream.

**One node is a human.** `annotation` requires `expert_labels`, and nothing in
the registry produces `expert_labels`. The reviewer is a producer in this
graph, and the gate is the check that their node has fired. That is not a
metaphor; it is how `FULL_INPUTS` is assembled.

## What that buys: the model never emits a plan

Because the graph derives the path from the goal, a model has no reason to
produce an ordered list of tool calls. It produces a **goal set** — one or a few
terminal tool names from a fixed vocabulary of twelve — and `order_plan` derives
the rest.

The output surface collapses from "an ordered sequence of calls with parameters"
to "a subset of twelve known strings", and the check is one line: is every name
in `list_plannable()`? Everything that goes wrong in a conventional agent loop
then becomes structurally impossible rather than merely unlikely:

| Failure mode | Why it cannot happen |
| --- | --- |
| wrong ordering | topological sort, not the model |
| forgotten dependency | `order_plan` inserts it |
| duplicated work | `if name in resolved: return` |
| invented tool | `unknown_tools()` rejects it by name |
| silently changed statistics | parameters come from `DEFAULT_PARAMS` |

That last row is the one most easily overlooked. `resolution=0.55`,
`n_perms=250`, `random_state=0` are tuned values. A model that picks `n_perms`
is a model quietly changing the p-values, and nothing downstream would notice.

**Reproducibility is the strongest argument.** Two models, or one model on two
phrasings of the same question, produce the same goal set and therefore a
byte-identical plan. Free-form tool calling destroys that property. Goal-set
emission preserves it. For an instrument whose reports are sent to
collaborators, that is not a nicety.

The usual pattern — hand the model the tool schemas and let it loop until it
decides it is finished — puts the model in charge of sequencing and termination.
Those are exactly the two things this DAG already does correctly, deterministically
and for free.

## Where the LLM belongs

**Routing intent to a goal set.** This is the clearest case and the weakest part
of the system today. The keyword table has produced real failures: `healthy` was
a keyword for `multi_sample_comparison`, so asking what a section named "Healthy
Brain" looks like was answered *"the tool for it is a scaffold"* — specific,
confident and wrong. `near` matched inside "near the top of the section" and
routed a question about position to a permutation test on the spatial graph.

A model is better at this, and being wrong is cheap and caught: an invented tool
is rejected by name, a gated step is refused by the gate, and a malformed plan
fails `validate_tool_plan`. The verification already exists and is already
tested.

**Proposing labels during review.** `cluster_label_worksheet.csv` already
carries `top_markers` per cluster — `LUM, CCDC80, MMP2, SFRP4, POSTN` is a
fibroblast and a model will say so. Two conditions make this safe, and both are
already enforced for other proposers:

- it writes `expert_cell_labels_candidate.csv`, never `expert_cell_labels.csv`,
  the same distinction `cell_regions_candidate.csv` has always maintained;
- `reviewer_id` names the model, so the proposal is attributable in the same
  column a person's review now fills in.

And a model's proposal is checked by the same machinery as anyone's:
`audit_labels_against_markers` reads each label back against the cells' own
markers and reports where they disagree.

## Where the LLM must never be

**The statistics.** Moran's I, Leiden, permutation tests, marker ranking. Not
worth arguing about, but worth writing down.

**The gate.** It is a predicate over evidence — coverage, class count, region
count, assets. A model deciding a section "looks reviewed enough" removes the
only thing that makes a validated claim mean anything.

**Assigning the reviewed labels.** A model may propose into the candidate file.
It may never write the reviewed table. The product's thesis is that naming a
cell type requires a human, and a model writing that table is the thesis
failing quietly.

**Claim reliability.** `S`, `A`, `P`, `R` are computed from evidence. A
generated score is fabrication with a number attached.

**The caveats.** This is the subtle one. The targeted-panel caveat and the
single-section caveat are valuable *precisely because they are mechanical*: they
cannot be forgotten, softened, or dropped when inconvenient. A model writing the
limitations section would be a regression wearing the costume of an improvement.

The single narrow exception after the gate: a plain-language summary of a
finished run, generated from numbers handed to it, never from numbers it
recalls, sitting above the templated report rather than replacing any part of
it.

## What the legacy path used to do, and what it does now

`spatialmind/planner.py` — reachable from the CLI and the API — did three things
this document says not to. All three were removed by making its output a goal
set, which is the demonstration that the argument above is not merely tidy.

1. **It dropped unknown tools silently.** `_steps_from_llm_payload` did
   `if tool not in ALLOWED_TOOLS: continue`. That is the same bug class the app
   planner already fixed: dropped names produced an empty plan and a run
   reporting success having done nothing. `unknown_tools()` exists because *a
   silent success on nothing is the one outcome this project is built to
   refuse*. Now `goals_from_payload` returns the rejected names and the plan
   carries them as a clarification; a payload naming nothing runnable falls back
   to the rules and says so, rather than returning an empty plan.
2. **It took parameters from the model.** `parameters = dict(parameters)`
   straight off the payload. A payload asking for `bin_size: 999.0` now gets
   `20.0`, because `build_steps` reads parameters from the parsed request and
   the payload's are never consulted.
3. **It took `depends_on` from the model.** `order_goals` derives every edge
   from `GOAL_REQUIRES`. This also fixed a latent bug: asking for
   co-localization alone produced one step whose `depends_on` named a step that
   was not in the plan. The producer is inserted now.

One function builds a step, and both the rule path and the model path call it,
so a plan the model asked for and a plan the rules derived cannot differ in
anything but which goals are in them. An old-shaped payload carrying whole steps
is still accepted and read for its tool names only.

## The economy argument, which points the same way

Minimising the model's work is usually framed as a cost decision, and here it
coincides exactly with the correctness decision. A model emitting a handful of
tokens is cheaper, faster, and covered by the tests that already exist. A model
emitting a plan is expensive, slower, and covered by hope. It is unusual for the
cheap option and the rigorous option to be the same option; when they are, take
it.
