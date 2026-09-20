"""The guided workflow behind the Studio's Create button.

Four steps, in order: take a dataset, take whatever the user typed, ask a short
list of questions the dataset can actually answer, and propose tools.

Two rules shape all of it.

**Nothing here invents a capability.** Every question offered, and every tool
proposed, resolves to a registered, implemented tool through `planner`. A
question the app cannot answer is not asked -- a wizard that collects an
intention it will later refuse has wasted the user's time and taught them the
gate is arbitrary.

**Nothing here routes around the gate.** Steps are labelled with the lane they
will run in, and a gate-blocked step says what is missing while it is still a
choice, not after the run fails.

The text analysis is deterministic and local. An LLM can phrase the restatement
more fluently, but it can also quietly widen the question past what the tools
do, and this is the step that decides what gets run.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

from . import planner

# A question is offered only when its tools are plannable and its inputs exist.
# `needs` names what the dataset must already carry; `lane` is what the user
# gets if they pick it.
MAX_SUGGESTED_QUESTIONS = 5

# Words that carry no intent, stripped before matching so "can you please show
# me the spatial structure" matches on "spatial structure".
_FILLER = {
    "please", "could", "would", "can", "you", "the", "a", "an", "of", "in", "for",
    "me", "my", "we", "our", "i", "is", "are", "to", "and", "with", "this", "that",
    "it", "on", "do", "does", "show", "tell", "give", "want", "like", "would",
    "help", "analyse", "analyze", "analysis", "data", "dataset", "sample",
}

_GENE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9\-]{1,14}\b")


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9_+\-]+", (text or "").lower())
    return [word for word in words if word not in _FILLER]


def mentioned_genes(text: str, panel: Sequence[str]) -> List[str]:
    """Gene symbols in the text that this panel actually measures.

    Checked against the panel rather than a general gene list on purpose: on a
    targeted assay the useful answer to "show me GFAP" is whether GFAP is one of
    the 300 genes on the slide, and a symbol the panel does not carry has to be
    reported as unmeasured rather than quietly dropped.
    """
    if not panel:
        return []
    known = {str(name).upper(): str(name) for name in panel}
    found: List[str] = []
    for token in _GENE_TOKEN.findall(text or ""):
        name = known.get(token.upper())
        if name and name not in found:
            found.append(name)
    return found


def unmeasured_genes(text: str, panel: Sequence[str]) -> List[str]:
    """Symbols that look like genes and are not on the panel.

    Reported so "absent" is never mistaken for "not expressed" -- the single
    most common misreading of a targeted panel.
    """
    if not panel:
        return []
    known = {str(name).upper() for name in panel}
    # Only tokens that look like a gene rather than an acronym in prose.
    skip = {"DNA", "RNA", "QC", "PCA", "UMAP", "ROI", "FFPE", "TSV", "CSV", "PDF"}
    found: List[str] = []
    for token in _GENE_TOKEN.findall(text or ""):
        upper = token.upper()
        if upper in known or upper in skip or len(upper) < 3:
            continue
        if upper not in found:
            found.append(upper)
    return found


def mentioned_labels(text: str, labels: Sequence[str]) -> List[str]:
    """Reviewed cell types or regions named in the text, matched loosely.

    `Invasive_Tumor`, `invasive tumor` and `invasive tumour` are the same class
    to a person typing a question.
    """
    if not labels:
        return []
    haystack = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    haystack = haystack.replace("tumour", "tumor")
    found: List[str] = []
    for label in labels:
        needle = re.sub(r"[^a-z0-9]+", " ", str(label).lower()).replace("tumour", "tumor").strip()
        if not needle or label in found:
            continue
        if needle in haystack:
            found.append(label)
            continue
        # `Myoepi_ACTA2+` is written "myoepithelial" by a person, and the full
        # class name will never appear in prose. So a leading token counts when
        # the word in the text *extends* it -- "myoepi" inside "myoepithelial".
        #
        # The extension is the whole rule. Without it, "invasive tumour cells"
        # matched the regions `tumor_rich`, `tumor_rich_b`, `tumor_rich_c` ...
        # on their shared `tumor` prefix, and the restatement promised to
        # restrict the run to five regions the user had never mentioned. A head
        # that equals a whole word in the text is ordinary prose, not a
        # reference to a label; only a genuine abbreviation counts.
        head = needle.split(" ")[0]
        if len(head) >= 5 and re.search(r"\b%s[a-z]" % re.escape(head), haystack):
            found.append(label)
    return found


def analyze_text(text: str, facts: Optional[Dict[str, Any]] = None,
                 tools: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Turn free text into a structured prompt this app can act on.

    Returns what was understood, what could not be, and the tools it implies --
    separately, so the UI can show the user the gap rather than an answer that
    silently narrowed their question.

    `tools` is for text that already resolved to a plan -- a suggested question
    the app itself offered. Matching such a question's own words again is a
    round trip through a keyword table that was never asked to round-trip, and
    it failed: "Which genes vary across tissue space in this section?" is
    generated by `recommend_questions` and matched no intent, because the
    keyword is "varies across".
    """
    facts = facts or {}
    raw = (text or "").strip()
    panel = list(facts.get("panel") or [])
    cell_types = list(facts.get("cell_types") or [])
    regions = list(facts.get("regions") or [])

    if not raw:
        return {
            "status": "empty",
            "prompt": "",
            "understood": [],
            "not_supported": [],
            "entities": {"genes": [], "unmeasured": [], "cell_types": [], "regions": []},
            "tools": [],
            "questions": [],
            "note": "Describe what you want to find out, or pick one of the suggested questions.",
        }

    lowered = raw.lower()
    plannable = {tool.name for tool in planner._registry().list_plannable()}

    # Both of the app's routing surfaces match through the planner, so a keyword
    # fix lands in both. This one had its own copy of the substring match and so
    # had its own copy of the bug.
    matched = planner.match_intents(lowered)
    missing, possible = planner.match_unavailable(lowered, plannable)

    resolved: List[str] = []
    understood: List[str] = []
    if tools:
        resolved = [name for name in tools if name in plannable]
        understood.append("Using the tools this suggested question resolves to.")
    else:
        for intent in matched:
            understood.append(intent["rationale"])
            for name in intent["tools"]:
                if name not in resolved:
                    resolved.append(name)
    tools = resolved

    entities = {
        "genes": mentioned_genes(raw, panel),
        "unmeasured": unmeasured_genes(raw, panel),
        "cell_types": mentioned_labels(raw, cell_types),
        "regions": mentioned_labels(raw, regions),
    }

    not_supported = [
        "%s: the tool for this (`%s`) is registered but is a scaffold -- it returns a "
        "placeholder and does no work, so it is not offered." % (_intent_phrase(intent), intent["tool"])
        for intent in missing
    ]
    # Suggestive matches are a guess at the question, so they are phrased as one
    # and they do not decide `status`: a question the app could not place is
    # "unclear", not "unsupported".
    not_supported += [
        "If you meant %s: the tool for it (`%s`) is registered but is a scaffold -- this is a guess at your "
        "question, not a reading of what it needs." % (_intent_phrase(intent), intent["tool"])
        for intent in possible
    ]

    status = "understood" if tools else ("unsupported" if missing else "unclear")
    return {
        "status": status,
        "prompt": restate(raw, tools, entities, facts),
        "understood": understood,
        "not_supported": not_supported,
        "entities": entities,
        "tools": planner.order_plan(tools) if tools else [],
        "questions": clarifying_questions(raw, tools, entities, facts),
        "note": _analysis_note(status, tools, missing, entities),
    }


def _intent_phrase(intent: Dict[str, Any]) -> str:
    return str(intent["tool"]).replace("_", " ").capitalize()


def _analysis_note(status: str, tools: List[str], missing: List[Any], entities: Dict[str, Any]) -> str:
    if status == "unsupported":
        return ("Everything in that question routes to a tool that is not implemented. "
                "Nothing has been added to the plan.")
    if status == "unclear":
        return ("No implemented tool clearly matches that. Pick a suggested question, or "
                "open the Tools tab and choose directly.")
    note = "Matched %d tool%s." % (len(tools), "" if len(tools) == 1 else "s")
    if entities.get("unmeasured"):
        note += (" %s is not on this panel, so nothing can be said about it: on a targeted assay "
                 "an absent gene was not measured, which is not the same as not expressed."
                 % ", ".join(entities["unmeasured"][:3]))
    return note


def restate(text: str, tools: List[str], entities: Dict[str, Any], facts: Dict[str, Any]) -> str:
    """The question as the app will actually act on it.

    Shown to the user before anything runs. A restatement that is narrower than
    what they asked is the point -- it is where they get to notice.
    """
    if not tools:
        return text.strip()
    parts = ["On %s," % (facts.get("display_name") or "this dataset")]
    steps = ", ".join("`%s`" % name for name in tools)
    parts.append("run %s" % steps)
    focus: List[str] = []
    if entities.get("genes"):
        focus.append("focusing on %s" % ", ".join(entities["genes"][:6]))
    if entities.get("cell_types"):
        focus.append("for %s" % ", ".join(entities["cell_types"][:6]))
    if entities.get("regions"):
        focus.append("within %s" % ", ".join(entities["regions"][:6]))
    if focus:
        parts.append(" ".join(focus))
    return " ".join(parts).rstrip(",") + "."


def clarifying_questions(text: str, tools: List[str], entities: Dict[str, Any],
                         facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Only questions whose answer changes the plan.

    A wizard that asks five questions to look thorough trains people to click
    through it. Each of these sets a parameter or picks a lane.
    """
    questions: List[Dict[str, Any]] = []
    if not tools:
        # Nothing matched, so there is no plan to shape. Asking about scope here
        # would be the wizard collecting an answer it has no use for.
        return questions
    gate_open = bool(facts.get("gate_open"))
    cell_types = list(facts.get("cell_types") or [])

    if any(name in tools for name in ("marker_detection", "differential_expression",
                                      "cell_neighborhood_enrichment", "neighborhood_enrichment")):
        if gate_open and cell_types:
            questions.append({
                "id": "group_key",
                "question": "Group by reviewed cell types, or by unsupervised clusters?",
                "options": [
                    {"value": "cell_type", "label": "Reviewed cell types (%d)" % len(cell_types)},
                    {"value": "leiden", "label": "Unsupervised clusters"},
                ],
                "default": "cell_type",
                "why": "Cell-type grouping is the validated lane. Clusters are data-derived and are never named.",
            })
        else:
            questions.append({
                "id": "group_key",
                "question": "No reviewed labels here, so grouping falls to clusters. Continue?",
                "options": [
                    {"value": "leiden", "label": "Yes, use unsupervised clusters"},
                ],
                "default": "leiden",
                "why": "Descriptive lane only. Results describe data-derived groups and name no cell type.",
            })

    if "spatial_variable_genes" in tools:
        questions.append({
            "id": "n_top",
            "question": "How many top spatially variable genes to report?",
            "options": [{"value": "25", "label": "25"}, {"value": "50", "label": "50 (default)"},
                        {"value": "100", "label": "100"}],
            "default": "50",
            "why": "Genes are screened before permutation testing; the report states the rule either way.",
        })

    if any(name in tools for name in ("cell_neighborhood_enrichment", "neighborhood_enrichment")):
        questions.append({
            "id": "n_perms",
            "question": "Permutations for the neighbourhood test?",
            "options": [{"value": "250", "label": "250 (fast)"}, {"value": "999", "label": "999 (tighter p-values)"}],
            "default": "250",
            "why": "More permutations narrow the null, at a proportional cost in runtime.",
        })

    if "feature_overlay" in tools:
        # Asked even when a gene was detected, with that gene pre-filled: the
        # tool takes exactly one feature, and picking silently when the text
        # named three is how the wrong gene gets plotted.
        genes = entities.get("genes") or []
        questions.append({
            "id": "feature",
            "question": "Which gene should be overlaid?",
            "options": [{"value": gene, "label": gene} for gene in genes[:6]],
            "default": genes[0] if genes else "",
            "why": ("feature_overlay draws one feature; it needs a name from the panel."
                    if not genes else
                    "Detected in your text. feature_overlay draws one feature at a time."),
        })

    n_cells = int(facts.get("n_cells") or 0)
    if n_cells > 60000:
        questions.append({
            "id": "scope",
            "question": "Run on the full section (%s cells) or a fast sample?" % format(n_cells, ","),
            "options": [
                {"value": "full", "label": "Full section -- slower, required for final claims"},
                {"value": "sample", "label": "Sample -- fast, marked as provisional"},
            ],
            "default": "full" if gate_open else "sample",
            "why": "A sampled run is labelled a deterministic sample in every report; biological claims need the full section.",
        })

    return questions[:MAX_SUGGESTED_QUESTIONS]


def recommend_questions(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Short questions this dataset can actually answer, best first.

    Grounded in what the dataset carries: its own cell types when the gate is
    open, its own clusters when it is not, its own panel genes. A generic list
    would offer cell-type questions on an unlabelled section, which is how a
    user learns to distrust the suggestions.
    """
    gate_open = bool(facts.get("gate_open"))
    cell_types = [str(name) for name in (facts.get("cell_types") or [])]
    regions = [str(name) for name in (facts.get("regions") or [])]
    panel = [str(name) for name in (facts.get("panel") or [])]
    n_clusters = int(facts.get("n_clusters") or 0)

    suggestions: List[Dict[str, Any]] = []

    def add(question: str, tools: List[str], why: str, lane: str) -> None:
        suggestions.append({"question": question, "tools": tools, "why": why, "lane": lane})

    # Label-free first when the gate is shut: these are the ones that will run.
    if gate_open and len(cell_types) >= 2:
        a, b = cell_types[0], cell_types[1]
        add("Which cell types sit next to each other more often than chance?",
            ["qc_and_cluster", "annotation", "cell_neighborhood_enrichment"],
            "A permutation test on the spatial graph over the %d reviewed cell types." % len(cell_types),
            "validated")
        add("Is %s spatially clustered, or spread evenly across the section?" % a,
            ["qc_and_cluster", "annotation", "cell_neighborhood_enrichment"],
            "Cell-type autocorrelation and point-pattern statistics over the reviewed labels.",
            "validated")
        add("Which genes mark %s against every other cell type?" % b,
            ["qc_and_cluster", "annotation", "marker_detection"],
            "One-vs-rest marker detection grouped by the reviewed label table.",
            "validated")
    else:
        add("Which genes vary across tissue space in this section?",
            ["qc_and_cluster", "spatial_variable_genes"],
            "A property of the expression field; no labels needed.",
            "descriptive")
        add("What structure does unsupervised clustering find here?",
            ["qc_and_cluster"],
            "Leiden clustering on expression. These are data-derived groups, never named as cell types.",
            "descriptive")
        add("Which genes distinguish each cluster from the rest?",
            ["qc_and_cluster", "marker_detection"],
            "One-vs-rest markers per cluster, which is also what a reviewer reads before labelling.",
            "descriptive")

    if gate_open and len(regions) >= 2:
        add("How does composition differ between %s and %s?" % (regions[0], regions[1]),
            ["qc_and_cluster", "annotation", "region_summary"],
            "Per-region cell-type composition and feature means over the reviewed regions.",
            "validated")
    elif n_clusters >= 2:
        add("Which clusters are neighbours in space?",
            ["qc_and_cluster", "cell_neighborhood_enrichment"],
            "Adjacency between data-derived clusters; the same test the validated lane runs on labels.",
            "descriptive")

    if panel:
        add("Where is %s expressed across the section?" % panel[0],
            ["feature_overlay"],
            "Single-feature overlay, guarded against genes absent from this %d-gene panel." % len(panel),
            "descriptive")

    return suggestions[:MAX_SUGGESTED_QUESTIONS]


def recommend_tools(tools: Sequence[str], gate_open: bool,
                    overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The tool list as a reviewable plan: order, lane, and what each blocks on.

    This is `planner.describe_plan` plus the reason each tool is in the list, so
    the selection screen and the thing that runs cannot disagree.
    """
    described = planner.describe_plan(list(tools), gate_open, overrides=overrides)
    catalog = {entry["name"]: entry for entry in planner.tool_catalog(gate_open)}
    for step in described.get("steps", []):
        entry = catalog.get(step.get("tool") or step.get("name")) or {}
        step["method"] = entry.get("method", "")
        step["estimated_runtime"] = entry.get("estimated_runtime", "")
        step["requires_labels"] = entry.get("requires_labels", False)
        step["requires_regions"] = entry.get("requires_regions", False)
        step["when_not_to_use"] = entry.get("when_not_to_use", "")
    return described


def apply_answers(tools: Sequence[str], answers: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Turn the wizard's answers into per-tool parameter overrides.

    Only the parameters the questions actually asked about. An answer that does
    not map to a real parameter is dropped rather than passed through, because
    `validate_tool_plan` would reject it and the user would see a plan error for
    a question this module asked them.
    """
    overrides: Dict[str, Dict[str, Any]] = {}
    names = set(tools)

    group_key = answers.get("group_key")
    if group_key in ("cell_type", "leiden"):
        for tool in ("marker_detection", "differential_expression",
                     "cell_neighborhood_enrichment", "neighborhood_enrichment"):
            if tool in names:
                overrides.setdefault(tool, {})["group_key"] = group_key

    if "spatial_variable_genes" in names:
        try:
            n_top = int(answers.get("n_top") or 0)
        except (TypeError, ValueError):
            n_top = 0
        if n_top > 0:
            overrides.setdefault("spatial_variable_genes", {})["n_top"] = n_top

    try:
        n_perms = int(answers.get("n_perms") or 0)
    except (TypeError, ValueError):
        n_perms = 0
    if n_perms > 0:
        for tool in ("cell_neighborhood_enrichment", "neighborhood_enrichment"):
            if tool in names:
                overrides.setdefault(tool, {})["n_perms"] = n_perms

    feature = str(answers.get("feature") or "").strip()
    if feature and "feature_overlay" in names:
        overrides.setdefault("feature_overlay", {})["feature"] = feature

    return overrides


def dataset_facts(detail: Dict[str, Any], panel: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Flatten a dataset detail response into what this module reasons over."""
    dataset = detail.get("dataset") or {}
    gate = detail.get("gate") or {}
    return {
        "dataset_id": dataset.get("dataset_id", ""),
        "display_name": dataset.get("display_name") or dataset.get("name") or "this dataset",
        "data_type": dataset.get("data_type", ""),
        "n_cells": detail.get("n_cells") or 0,
        "gate_open": (gate.get("status") == "validated_ready"),
        "gate_status": gate.get("status", "unknown"),
        "blocking_reasons": list(gate.get("blocking_reasons") or []),
        "cell_types": list(gate.get("cell_classes") or gate.get("reviewed_labels") or []),
        "regions": list(gate.get("regions") or gate.get("reviewed_regions") or []),
        "n_clusters": len(detail.get("cluster_sizes") or {}),
        "panel": list(panel or []),
    }
