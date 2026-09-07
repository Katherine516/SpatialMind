"""What is needed to produce expert cell labels, and what is already here.

The gate blocks on two files the agent may not write for itself. "Add expert
labels" is true but useless as an instruction, so this reports the actual
inputs -- references, ontology vocabulary, reviewer time -- and which of them
the workspace already has.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from .catalog import pretty_name, resolve_xenium_root
from .review import table_path

# A transfer can only name lineages its reference carries, so a reference set is
# judged by which of these it covers, not by how many cells it holds.
BRAIN_LINEAGES = ("astrocyte", "oligodendrocyte", "opc", "myeloid", "neuronal", "endothelial", "stromal")
REFERENCE_HINTS = {
    "astrocyte": ("astrocyte",),
    "oligodendrocyte": ("oligodendrocyte",),
    "opc": ("precursor", "opc"),
    "myeloid": ("microglia", "myeloid", "macrophage"),
    "neuronal": ("neuron", "intratelencephalic", "splatter", "gabaergic"),
    "endothelial": ("vascular", "endothelial"),
    "stromal": ("vascular", "fibroblast", "stromal", "mural"),
}


def _size_gb(path: Path) -> float:
    try:
        return round(path.stat().st_size / (1024 ** 3), 2)
    except OSError:
        return 0.0


def find_references(data_root: str) -> List[Dict[str, Any]]:
    root = Path(data_root)
    if not root.is_dir():
        return []
    references = []
    for path in sorted(root.rglob("*.h5ad")):
        name = path.name
        lowered = name.lower()
        covers = sorted({
            lineage for lineage, hints in REFERENCE_HINTS.items()
            if any(hint in lowered for hint in hints)
        })
        references.append({
            "name": name,
            "display_name": pretty_name(name),
            "relative_path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
            "size_gb": _size_gb(path),
            "covers": covers,
        })
    return references


def lineage_coverage(references: List[Dict[str, Any]]) -> Dict[str, Any]:
    covered = sorted({lineage for ref in references for lineage in ref["covers"]})
    missing = [lineage for lineage in BRAIN_LINEAGES if lineage not in covered]
    return {"covered": covered, "missing": missing, "lineages": list(BRAIN_LINEAGES)}


def dataset_state(dataset_path: Optional[str], gate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Whether the tables exist *and* whether they satisfy the gate.

    Existence is not the same as sufficiency, and reporting it as though it were
    is worse than saying nothing: a stray table naming one region over 8.8% of
    the section made this panel read "have" while the gate read "blocked" three
    inches above it. When the gate's numbers are available they decide.
    """
    if not dataset_path:
        return {}
    root = resolve_xenium_root(Path(dataset_path))
    state = {
        "has_labels": table_path(str(root), "labels").exists(),
        "has_regions": table_path(str(root), "regions").exists(),
        "label_template": (root / "expert_label_template.csv").exists(),
        "region_template": (root / "region_label_template.csv").exists(),
    }
    if gate:
        state.update({
            "label_coverage": gate.get("label_coverage"),
            "region_coverage": gate.get("region_coverage"),
            "cell_classes": len(gate.get("cell_classes") or []),
            "regions": len(gate.get("regions") or []),
            "min_label_coverage": gate.get("min_label_coverage", 0.7),
            "min_region_coverage": gate.get("min_region_coverage", 0.7),
        })
        state["labels_sufficient"] = (
            (state.get("label_coverage") or 0) >= state["min_label_coverage"] and state["cell_classes"] >= 2)
        state["regions_sufficient"] = (
            (state.get("region_coverage") or 0) >= state["min_region_coverage"] and state["regions"] >= 2)
    return state


def _table_status(state: Dict[str, Any], kind: str) -> str:
    """`have` only when the table would actually clear the gate."""
    present = state.get("has_labels" if kind == "labels" else "has_regions")
    sufficient = state.get("labels_sufficient" if kind == "labels" else "regions_sufficient")
    if sufficient:
        return "have"
    return "partial" if present else "missing"


def _table_detail(state: Dict[str, Any], kind: str) -> str:
    if kind == "labels":
        present, coverage, count, noun = state.get("has_labels"), state.get("label_coverage"), state.get("cell_classes"), "class"
        filename, threshold = "expert_cell_labels.csv", state.get("min_label_coverage") or 0.7
    else:
        present, coverage, count, noun = state.get("has_regions"), state.get("region_coverage"), state.get("regions"), "region"
        filename, threshold = "cell_regions.csv", state.get("min_region_coverage") or 0.7
    if not present:
        return ("No %s for this dataset." % filename) + (
            " No reference or model can supply this: tumour core versus infiltrating edge is a judgement "
            "about this section." if kind == "regions" else
            " Roughly 1,600 labelled cells at a 2,000-cell run; a 500-cell run clears coverage and then "
            "fails on per-class statistics.")
    if coverage is None:
        return "%s present." % filename
    return ("%s covers %.1f%% of the section across %d %s%s; the gate needs %d%% and at least two."
            % (filename, float(coverage) * 100, count or 0, noun, "" if count == 1 else "s",
               round(float(threshold) * 100)))


def inventory(data_root: str, dataset_path: Optional[str] = None,
              gate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    references = find_references(data_root)
    coverage = lineage_coverage(references)
    ontology_dir = Path(data_root) / "cell_ontology_terms"
    ontology_terms = sorted(p.stem for p in ontology_dir.glob("*.json")) if ontology_dir.is_dir() else []
    state = dataset_state(dataset_path, gate)

    requirements: List[Dict[str, Any]] = [
        {
            "id": "reference_normal",
            "title": "Reference atlas for the normal lineages",
            "status": "have" if not coverage["missing"] else ("partial" if references else "missing"),
            "detail": (
                "%d reference file%s covering %s."
                % (len(references), "" if len(references) == 1 else "s", ", ".join(coverage["covered"]) or "nothing")
                if references else "No .h5ad reference found under the data root."
            ),
            "action": (
                "" if not coverage["missing"]
                else "Add a reference carrying: %s. A transfer cannot name a lineage its reference lacks; "
                     "it assigns the nearest available class instead, usually at high confidence."
                     % ", ".join(coverage["missing"])
            ),
            "unblocks": "Candidate labels for expert review (Route B).",
        },
        {
            "id": "reference_malignant",
            "title": "Human reference carrying a malignant class",
            "status": "missing",
            "detail": "No human tumour reference present. A normal-brain atlas can name astrocyte or "
                      "oligodendrocyte but never neoplastic cell, which is the central call in a tumour section.",
            "action": "Add a human glioma/GBM scRNA reference with a neoplastic or malignant class "
                      "(for example a cellxgene GBM dataset). A mouse reference cannot substitute: the "
                      "preflight refuses cross-species transfer.",
            "unblocks": "Candidate labels that can distinguish tumour from reactive glia.",
        },
        {
            "id": "ontology",
            "title": "Controlled label vocabulary",
            "status": "have" if ontology_terms else "partial",
            "detail": ("%d Cell Ontology term file%s cached; the labelling guide carries the broad vocabulary."
                       % (len(ontology_terms), "" if len(ontology_terms) == 1 else "s"))
                      if ontology_terms else
                      "No cached Cell Ontology terms under the data root.",
            "action": "" if ontology_terms else
                      "Optional. Review Studio ships the common terms; cache more into "
                      "<data root>/cell_ontology_terms/ if reviewers need the full definitions offline.",
            "unblocks": "Labels that mean the same thing across reviewers and datasets.",
        },
        {
            "id": "reviewer",
            "title": "Expert reviewer time",
            "status": "missing",
            "detail": "Roughly 1,600 labelled cells at a 2,000-cell run. Measured: a 500-cell run clears the "
                      "70% coverage gate and then fails on per-class statistics.",
            "action": "A neuropathologist or equivalent, working in Review Studio or in Xenium Explorer / "
                      "QuPath and exporting the same CSV.",
            "unblocks": "expert_cell_labels.csv, which is the only labels the gate accepts.",
        },
        {
            "id": "regions",
            "title": "Region delineation",
            "status": _table_status(state, "regions"),
            "detail": _table_detail(state, "regions"),
            "action": "" if state.get("regions_sufficient") else
                      "Draw at least two regions covering %d%% of the section in Review Studio."
                      % round(float(state.get("min_region_coverage") or 0.7) * 100),
            "unblocks": "Region summaries and any region-stratified claim.",
        },
    ]
    if state.get("has_labels"):
        for requirement in requirements:
            if requirement["id"] == "reviewer":
                requirement["status"] = _table_status(state, "labels")
                requirement["detail"] = _table_detail(state, "labels")
                if state.get("labels_sufficient"):
                    requirement["action"] = ""

    return {
        "data_root": data_root,
        "references": references,
        "lineage_coverage": coverage,
        "ontology_terms": ontology_terms,
        "dataset_state": state,
        "requirements": requirements,
        "outstanding": [r["id"] for r in requirements if r["status"] != "have"],
    }
