"""The tool catalog, plan assembly, and question routing for the Studio.

Three surfaces in the app choose tools -- Ask, recipes, and the Tool Bench --
and all three land here, producing the same `ToolCallSpec` list that the real
`validate_tool_plan` checks. Nothing in the UI gets its own idea of what a valid
plan is.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..agent.runtime import (
    DEFAULT_XENIUM_INPUTS,
    MVP_TOOL_OUTPUTS,
    build_xenium_mvp_plan,
    validate_tool_plan,
)
from ..contracts import ToolCallSpec
from ..gatekeeper import requires_labels, requires_regions
from ..tools import build_default_registry

# Plan validation checks *structure* against the full input set; whether those
# inputs actually exist is the gate's job. Validating against a reduced set here
# would duplicate the gate's blockers as fake plan errors.
FULL_INPUTS = list(DEFAULT_XENIUM_INPUTS) + ["expert_labels", "user_regions"]

# What each tool needs upstream, in the same output vocabulary the validator uses.
TOOL_REQUIRES: Dict[str, List[str]] = {
    "qc_and_cluster": ["normalized_counts"],
    "spatial_clustering": ["normalized_counts", "spatial_coords"],
    "annotation": ["clustering", "expert_labels"],
    "cell_type_annotation": ["normalized_counts"],
    "reference_label_transfer": ["normalized_counts"],
    "marker_detection": ["annotation"],
    "differential_expression": ["annotation"],
    "feature_overlay": ["normalized_counts"],
    "spatial_variable_genes": ["normalized_counts", "spatial_coords"],
    "region_summary": ["annotation", "user_regions"],
    "cell_neighborhood_enrichment": ["annotation", "spatial_coords"],
    "neighborhood_enrichment": ["annotation", "spatial_coords"],
}

DEFAULT_PARAMS: Dict[str, Dict[str, Any]] = {
    "qc_and_cluster": {"resolution": 0.55, "random_state": 0, "strict_engine": True},
    "spatial_clustering": {"resolution": 0.8, "n_neighbors": 15},
    "annotation": {"method": "expert_label_table"},
    "cell_type_annotation": {"method": "expert_label_table"},
    "reference_label_transfer": {"min_shared_features": 120},
    "marker_detection": {"group_key": "cell_type", "n_top": 25, "strict_engine": True},
    "differential_expression": {"group_key": "cell_type", "n_top": 25},
    "feature_overlay": {"feature": ""},
    "spatial_variable_genes": {
        "n_top": 50, "n_neighs": 6, "n_perms": 250, "random_state": 0, "strict_engine": True,
    },
    "region_summary": {"top_n_features": 10},
    "cell_neighborhood_enrichment": {
        "n_neighs": 6, "n_perms": 250, "random_state": 0, "include_all_pairs": True, "strict_engine": True,
    },
    "neighborhood_enrichment": {"n_neighs": 6, "n_perms": 250, "random_state": 0},
}

def _registry():
    return build_default_registry()


def lane_for(tool, gate_open: bool, params: Optional[Dict[str, Any]] = None) -> str:
    """`blocked`, `descriptive`, or `validated` for one tool as it would run now."""
    if tool.capability == "unavailable":
        return "unavailable"
    gated = requires_labels(tool, params) or requires_regions(tool)
    if gated and not gate_open:
        return "blocked"
    return "validated" if gate_open else "descriptive"


def tool_catalog(gate_open: bool = False) -> List[Dict[str, Any]]:
    """Every registered tool, scaffolds included and plainly marked."""
    registry = _registry()
    catalog: List[Dict[str, Any]] = []
    for tool in registry.list_all():
        params = DEFAULT_PARAMS.get(tool.name, {})
        catalog.append(
            {
                "name": tool.name,
                "description": tool.description,
                "when_to_use": tool.when_to_use,
                "when_not_to_use": tool.when_not_to_use,
                "capability": tool.capability,
                "plannable": tool.capability != "unavailable",
                "lane": lane_for(tool, gate_open, params),
                "requires_labels": requires_labels(tool, params),
                "requires_regions": requires_regions(tool),
                "preconditions": list(tool.preconditions),
                "estimated_runtime": tool.estimated_runtime,
                "requires": TOOL_REQUIRES.get(tool.name, []),
                "params": params,
                "method": getattr(tool.citation, "method_name", "") if tool.citation else "",
                "outputs": MVP_TOOL_OUTPUTS.get(tool.name, []),
            }
        )
    summary = registry.capability_summary()
    for entry in catalog:
        entry["registry_summary"] = summary
    return catalog


def capability_summary() -> Dict[str, int]:
    return _registry().capability_summary()


def unknown_tools(tool_names: Iterable[str]) -> List[str]:
    """Names that are not in the registry at all.

    Returned rather than dropped. `order_plan` filtered them out silently, so a
    request for a tool this build does not have produced an empty plan, a
    `plan_status: valid`, and -- through `POST /api/runs` -- a job that reported
    `succeeded` with no error and no results. A silent success on nothing is the
    one outcome this project is built to refuse.
    """
    known = {tool.name for tool in _registry().list_all()}
    return [name for name in dict.fromkeys(tool_names) if name not in known]


def order_plan(tool_names: Iterable[str]) -> List[str]:
    """Insert missing dependencies and sort so producers precede consumers."""
    registry = _registry()
    wanted = [name for name in dict.fromkeys(tool_names) if name in {t.name for t in registry.list_all()}]
    produced: Dict[str, str] = {}
    for name, outputs in MVP_TOOL_OUTPUTS.items():
        for output in outputs:
            produced.setdefault(output, name)

    resolved: List[str] = []

    def add(name: str, seen: Tuple[str, ...] = ()) -> None:
        if name in resolved or name in seen:
            return
        for key in TOOL_REQUIRES.get(name, []):
            producer = produced.get(key)
            if producer and producer != name:
                add(producer, seen + (name,))
        resolved.append(name)

    for name in wanted:
        add(name)
    return resolved


def build_plan(tool_names: Iterable[str], overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> List[ToolCallSpec]:
    overrides = overrides or {}
    plan: List[ToolCallSpec] = []
    for name in order_plan(tool_names):
        params = dict(DEFAULT_PARAMS.get(name, {}))
        params.update(overrides.get(name, {}))
        plan.append(ToolCallSpec(name, params, requires=list(TOOL_REQUIRES.get(name, []))))
    return plan


def describe_plan(tool_names: Iterable[str], gate_open: bool, overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    registry = _registry()
    plan = build_plan(tool_names, overrides=overrides)
    report = validate_tool_plan(
        plan,
        available_inputs=FULL_INPUTS,
        registry_tool_names=[tool.name for tool in registry.list_plannable()],
    )
    steps = []
    for index, spec in enumerate(plan):
        tool = registry.get(spec.tool_name)
        lane = lane_for(tool, gate_open, spec.params)
        steps.append(
            {
                "index": index + 1,
                "tool": spec.tool_name,
                "params": dict(spec.params),
                "requires": list(spec.dependency_keys()),
                "lane": lane,
                "runnable_now": lane in {"descriptive", "validated"},
                "estimated_runtime": tool.estimated_runtime,
                "method": getattr(tool.citation, "method_name", "") if tool.citation else "",
            }
        )
    runnable = [step for step in steps if step["runnable_now"]]
    # Unknown names never reach `plan`, so the structural validator cannot see
    # them. They are the caller's own words and have to come back.
    missing = unknown_tools(tool_names)
    errors = list(report.errors)
    for name in missing:
        errors.append("No tool named `%s` in this build." % name)
    if missing and not steps:
        errors.append("Nothing in that request names a tool that exists, so there is no plan.")
    return {
        "steps": steps,
        "unknown_tools": missing,
        "plan_status": "invalid" if errors else report.status,
        "plan_errors": errors,
        "runnable_steps": len(runnable),
        "blocked_steps": len(steps) - len(runnable),
        "estimated_minutes": round(sum(_minutes(step["estimated_runtime"]) for step in runnable), 1),
    }


def _minutes(runtime: str) -> float:
    text = (runtime or "").lower()
    if text.startswith("fast"):
        return 0.5
    if text.startswith("slow"):
        return 12.0
    return 4.0


def mvp_plan_names() -> List[str]:
    return [spec.tool_name for spec in build_xenium_mvp_plan()]


RECIPES: List[Dict[str, Any]] = [
    {
        "id": "descriptive",
        "title": "Descriptive QC lane",
        "summary": "Runs without labels. Clusters, per-cluster markers, spatially variable genes and cluster adjacency.",
        "tools": ["qc_and_cluster", "marker_detection", "spatial_variable_genes", "cell_neighborhood_enrichment"],
        "overrides": {
            "marker_detection": {"group_key": "leiden"},
            "cell_neighborhood_enrichment": {"group_key": "leiden"},
        },
    },
    {
        "id": "validated_pilot",
        "title": "Validated Xenium pilot",
        "summary": "The canonical gated plan: QC, annotation, markers, spatial genes, region summary, neighbourhoods.",
        "tools": mvp_plan_names(),
        "overrides": {},
    },
    {
        "id": "spatial_only",
        "title": "Spatial structure only",
        "summary": "Which genes vary across tissue space, with the screening rule recorded.",
        "tools": ["qc_and_cluster", "spatial_variable_genes"],
        "overrides": {},
    },
    {
        "id": "region_contrast",
        "title": "Region contrast",
        "summary": "Composition and feature means per reviewed region, plus cell-type adjacency.",
        "tools": ["qc_and_cluster", "annotation", "region_summary", "cell_neighborhood_enrichment"],
        "overrides": {},
    },
]


INTENTS: List[Dict[str, Any]] = [
    {
        # Not bare "near": "near the top of the section" is not an adjacency
        # question, and it used to route to a permutation test on the graph.
        "keywords": ("next to", "adjacent", "neighbour", "neighbor", "co-locali", "colocali",
                     "surround", "nearby", "near each other", "near one another"),
        "tools": ["qc_and_cluster", "annotation", "cell_neighborhood_enrichment"],
        "rationale": "Adjacency between named cell types is a permutation test on the spatial graph, so this routes to cell_neighborhood_enrichment after annotation.",
    },
    {
        "keywords": ("spatially variable", "spatial pattern", "varies across", "spatially structured", "moran"),
        "tools": ["qc_and_cluster", "spatial_variable_genes"],
        "rationale": "A property of the expression field itself, so no labels are needed. Genes are screened before permutation testing and the report states the rule.",
    },
    {
        "keywords": ("region", "roi", "tumor core", "tumour core", "compartment", "zone"),
        "tools": ["qc_and_cluster", "annotation", "region_summary"],
        "rationale": "Region questions need reviewed regions; region_summary reports composition and feature means per region.",
    },
    {
        "keywords": ("marker", "upregulated", "differential", "enriched gene", "signature"),
        "tools": ["qc_and_cluster", "marker_detection"],
        "rationale": "One-vs-rest marker detection over the available grouping; a pairwise contrast needs explicit group1 and group2.",
    },
    {
        "keywords": ("cluster", "domain", "structure", "group the cells", "unsupervised"),
        "tools": ["qc_and_cluster"],
        "rationale": "Leiden clustering on expression. These are data-derived groups and are never named as cell types.",
    },
    {
        # "population" is a prefix on purpose: it carries "populations" too.
        # "Which cell populations are present?" is the most natural form of this
        # question and used to fall through to "no confident route".
        "keywords": ("cell type", "which cells", "what cells", "annotate", "composition",
                     "abundance", "cell population", "population"),
        "tools": ["qc_and_cluster", "annotation"],
        "rationale": "Cell-type statements need the reviewed label table; annotation summarises what was applied.",
    },
    {
        "keywords": ("express", "overlay", "show gene", "where is"),
        "tools": ["feature_overlay"],
        "rationale": "Single-feature overlay, guarded against features absent from the targeted panel.",
    },
    {
        # An open "what am I looking at" question. Clustering plus the spatial
        # map is the honest answer to it, and it is the descriptive lane, so it
        # runs without the gate.
        "keywords": ("look like", "looks like", "overview", "describe this", "describe the",
                     "summarise this", "summarize this", "what is in this", "tell me about",
                     "get a sense", "first look"),
        "tools": ["qc_and_cluster"],
        "rationale": "An open question about the section: unsupervised clustering and the spatial map describe it without naming anything.",
    },
]

# Questions whose honest answer is "the tool for that is a scaffold". Naming the
# tool is the point: a user who is told which tool is missing can judge the gap.
#
# `keywords` are decisive: a term that means this analysis and little else, and
# is enough on its own to name the tool. `suggestive` are words that often
# accompany the analysis but are ordinary English besides -- "healthy" is a
# tissue descriptor, "segment" is cell segmentation far more often than tissue
# segmentation, "differentiation" collides with differential expression. They
# are reported as a possibility and never as a diagnosis.
#
# The split exists because "What does this healthy brain section look like?" was
# answered "the tool for it (multi_sample_comparison) is a scaffold" -- a
# confident, specific and wrong account of why the app would not help, which is
# the worst failure available to an app whose whole claim is that it refuses
# rather than guesses.
UNAVAILABLE_INTENTS: List[Dict[str, Any]] = [
    {"keywords": ("copy number", "cnv", "aneuploid", "malignant cells by"), "tool": "cnv_inference"},
    {"keywords": ("ligand", "receptor", "crosstalk", "signalling", "signaling", "cell-cell communication"),
     "suggestive": ("communication",), "tool": "ligand_receptor_analysis"},
    {"keywords": ("deconvolut", "cell type proportion", "proportions per spot"), "tool": "spatial_deconvolution"},
    {"keywords": ("pathway", "mapk", "pi3k", "tgfb"), "tool": "pathway_activity"},
    {"keywords": ("trajectory", "pseudotime"), "suggestive": ("differentiation",), "tool": "trajectory_inference"},
    {"keywords": ("across samples", "between samples", "across sections", "between sections",
                  "across donors", "between donors", "multi-sample", "multi sample"),
     "suggestive": ("compare", "versus", "vs ", "healthy"), "tool": "multi_sample_comparison"},
    {"keywords": ("transcription factor", "tf activity"), "suggestive": ("motif",),
     "tool": "transcription_factor_activity"},
    {"keywords": ("tissue segmentation", "h&e", "immunofluorescence", "histology"),
     "suggestive": ("segment",), "tool": "tissue_segmentation"},
    {"keywords": ("niche", "microenvironment"), "suggestive": ("exclusion",), "tool": "tumor_niche_analysis"},
]


_PATTERNS: Dict[str, Any] = {}


def _pattern(keyword: str):
    """A keyword matches at a word boundary and may run on as a prefix.

    Prefixes are deliberate -- `deconvolut` has to carry "deconvolution" and
    "deconvolute" -- so only the start is anchored. Plain substring matching is
    what let "near" fire inside "linear" and "nearly", routing a question about
    the top of a section to neighbourhood enrichment.
    """
    compiled = _PATTERNS.get(keyword)
    if compiled is None:
        compiled = re.compile(r"\b" + re.escape(keyword), re.IGNORECASE)
        _PATTERNS[keyword] = compiled
    return compiled


def _mentions(text: str, keywords: Iterable[str]) -> bool:
    return any(_pattern(keyword).search(text) for keyword in keywords)


def match_intents(text: str) -> List[Dict[str, Any]]:
    """Implemented routes whose keywords appear in the question."""
    return [intent for intent in INTENTS if _mentions(text, intent["keywords"])]


def match_unavailable(text: str, plannable: Iterable[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Scaffold routes the question points at: (named, possible).

    `named` earned a decisive keyword and may be reported as the reason. `possible`
    matched only a suggestive word, so it may be offered as a guess and must not
    be stated as a finding. A scaffold that the registry has since implemented is
    neither: the refusal would be on behalf of a tool that works.
    """
    plannable = set(plannable)
    named, possible = [], []
    for intent in UNAVAILABLE_INTENTS:
        if intent["tool"] in plannable:
            continue
        if _mentions(text, intent["keywords"]):
            named.append(intent)
        elif _mentions(text, intent.get("suggestive", ())):
            possible.append(intent)
    return named, possible


def _analysis_phrase(tools: List[str]) -> str:
    """`multi_sample_comparison` -> "multi sample comparison", for a sentence."""
    return " or ".join(name.replace("_", " ") for name in tools)


def propose(question: str, gate_open: bool) -> Dict[str, Any]:
    """Route a question to a plan, or refuse when no implemented tool answers it."""
    text = (question or "").lower().strip()
    registry = _registry()
    plannable = {tool.name for tool in registry.list_plannable()}

    if not text:
        return {
            "answer": "Ask about spatial structure, markers, regions, or cell-type relationships in this section.",
            "tools": [],
            "rationale": "",
            "refusal": None,
        }

    matched = match_intents(text)
    named, possible = match_unavailable(text, plannable)

    if named and not matched:
        names = ", ".join(sorted({intent["tool"] for intent in named}))
        return {
            "answer": (
                "I can't answer that. The tool for it (%s) is registered but is a scaffold: it returns a "
                "placeholder and does no work, so it is excluded from planning. Nothing else in the registry "
                "covers it." % names
            ),
            "tools": [],
            "rationale": "%d of %d registered tools are plannable; the rest are hidden from the planner rather than substituted."
            % (len(plannable), len(registry.list_all())),
            "refusal": names,
        }

    if not matched:
        # A suggestive word is a guess about what was meant, so it is offered as
        # one. Stating it as the reason is how "healthy brain section" came back
        # as "multi_sample_comparison is a scaffold": a specific, confident and
        # wrong account of why the app would not help.
        answer = (
            "I don't have a confident route for that. The Tool Bench lists every implemented tool with its "
            "preconditions if you want to drive it directly."
        )
        guesses = sorted({intent["tool"] for intent in possible})
        if guesses:
            answer += (
                " If you meant %s, that tool (%s) is registered but is a scaffold and does no work -- though I "
                "am guessing at your question, not reporting what it needs."
                % (_analysis_phrase(guesses), ", ".join(guesses))
            )
        return {
            "answer": answer,
            "tools": [],
            "rationale": "No intent matched, and guessing a tool would be worse than saying so.",
            "refusal": None,
            "possible_scaffolds": guesses,
        }

    tools: List[str] = []
    rationales: List[str] = []
    for intent in matched:
        for name in intent["tools"]:
            if name not in tools:
                tools.append(name)
        rationales.append(intent["rationale"])

    described = describe_plan(tools, gate_open)
    blocked = described["blocked_steps"]
    if blocked and not gate_open:
        answer = (
            "I can plan this, but %d of %d steps need reviewed labels or regions, which this dataset does not "
            "have yet. The rest runs now in the descriptive lane, which describes data-derived groups and never "
            "names a cell type." % (blocked, len(described["steps"]))
        )
    else:
        answer = "%d step%s, all runnable now." % (len(described["steps"]), "" if len(described["steps"]) == 1 else "s")

    # Only decisive matches earn this note: it is an assertion about the
    # question, and `possible` is a guess at one.
    if named:
        names = ", ".join(sorted({intent["tool"] for intent in named}))
        answer += " Note that %s is a scaffold, so any part of the question needing it is not answered here." % names

    return {
        "answer": answer,
        "tools": [step["tool"] for step in described["steps"]],
        "rationale": " ".join(rationales),
        "refusal": ", ".join(sorted({i["tool"] for i in named})) if named else None,
        # Empty by construction once a route exists: a guess about what the
        # question might have meant is only worth anything when nothing matched.
        "possible_scaffolds": [],
        "plan": described,
    }
