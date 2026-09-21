"""Machine-readable result tables, because a report is not a dataset.

A full validated run wrote fifteen JSON files, six images and two reports, and
zero tabular result files. The only CSVs it produced were the two review
templates. So the per-gene numbers a bench scientist would put in a supplementary
table -- or open in Excel, or read into R -- did not exist in any form they could
use, and `spatial_variable_genes.json` kept only the top fifty rows: 296 genes
detected, 100 tested, 50 written.

Four decisions here matter more than the file list:

**Long format.** One row per gene, or per (gene, cell). Loads into pandas, R or a
spreadsheet without reshaping, and a new column later does not break anyone's
script.

**TSV, not CSV.** The data already contains commas -- `Fibroblast/Stromal cell`
is a real label in these sections, and gene-set names are worse. Tabs are safe
without quoting rules nobody reads.

**Every table carries its own provenance.** `run_id`, dataset and gate status as
a header comment on every file. A TSV gets emailed detached from its report, and
the report's caveats have to travel with it -- otherwise the honesty work is
undone the moment someone opens the spreadsheet. This is the same argument that
made the HTML report inline its figures.

**`cells.tsv` never publishes a `cell_type` column on a blocked run.** On a
blocked run that column holds the loader's marker-rule guesses, which the
architecture doc says are never truth. A spreadsheet header saying `cell_type`
is a claim. When the gate is not open the column is named
`cell_type_provisional` and `label_source` sits beside it.
"""

import gzip
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from spatialmind.schemas import (
    NON_EXPRESSION_FEATURE_NAMES,
    SpatialDataset,
    is_control_feature,
)

TABLE_DIRNAME = "tables"

# Above this, `cells.tsv` is gzipped. A 378k-cell section at ~20 columns is tens
# of megabytes uncompressed, and the file is the one most likely to be attached
# to an email.
GZIP_ROW_THRESHOLD = 100_000


def write_result_tables(
    payload: Dict[str, Any],
    dataset: Optional[SpatialDataset],
    output_dir: Path,
    run_id: str = "",
    results: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Write every result table this run can support. Returns a manifest.

    `results` is the run's ToolResult list. The payload keeps summarised copies of
    some tool output and none of the rest, so a writer that read only the payload
    emitted no pair table and no region table at all -- the numbers were in the
    per-tool JSON files and nowhere the payload could see.
    """
    metrics_by_tool = _metrics_by_tool(results)
    tables_dir = Path(output_dir) / TABLE_DIRNAME
    tables_dir.mkdir(parents=True, exist_ok=True)
    header = _provenance_header(payload, run_id)
    written: List[Dict[str, Any]] = []

    for name, columns, rows in (
        ("genes_spatial.tsv", GENE_COLUMNS, _gene_rows(payload, metrics_by_tool)),
        ("cell_types_spatial.tsv", GROUP_COLUMNS, _group_rows(payload)),
        ("celltype_pairs.tsv", PAIR_COLUMNS, _pair_rows(payload, metrics_by_tool)),
        ("markers.tsv", MARKER_COLUMNS, _marker_rows(payload, metrics_by_tool)),
        ("region_composition.tsv", REGION_COLUMNS, _region_rows(payload, metrics_by_tool)),
        ("point_pattern.tsv", POINT_PATTERN_COLUMNS, _point_pattern_rows(payload)),
        ("gene_pair_spatial.tsv", GENE_PAIR_COLUMNS, _gene_pair_rows(payload)),
    ):
        rows = list(rows)
        if not rows:
            continue
        path = tables_dir / name
        _write_tsv(path, columns, rows, header)
        written.append({"table": name, "path": str(path), "rows": len(rows)})

    if dataset is not None and dataset.records:
        cell_table = _write_cells(payload, dataset, tables_dir, header)
        if cell_table:
            written.append(cell_table)

    manifest = {
        "status": "written" if written else "not_written",
        "directory": str(tables_dir),
        "format": "tsv",
        "tables": written,
        "note": (
            "Long-format result tables. Every file repeats the run id, dataset and gate status as "
            "a header comment, because a table is usually read apart from the report that "
            "qualifies it."
        ),
    }
    return manifest


GENE_COLUMNS = ["gene", "morans_i", "pval_norm", "pval_sim", "pval_adj",
                "tested", "detected_cells", "fdr_scope", "screen_rule"]
GROUP_COLUMNS = ["group", "group_kind", "morans_i", "pval_sim", "pval_adj", "n_cells",
                 "graph_family", "n_neighs", "interpretation"]
PAIR_COLUMNS = ["type_a", "type_b", "zscore", "is_self_pair", "n_a", "n_b",
                "tested_pair_count", "graph_family", "evidence_status", "allowed_interpretation"]
MARKER_COLUMNS = ["group", "group_kind", "gene", "rank", "marker_evidence"]
REGION_COLUMNS = ["region", "cell_type", "n_cells", "fraction", "region_total"]
POINT_PATTERN_COLUMNS = ["group", "n_cells", "peak_deviation", "peak_radius_um", "mean_deviation",
                         "radii_above_envelope", "radii_below_envelope", "deviation_sign_varies",
                         "verdict", "max_distance_um"]
GENE_PAIR_COLUMNS = ["gene_a", "gene_b", "lees_l", "pearson_r", "status", "interpretation"]


def _metrics_by_tool(results: Optional[Sequence[Any]]) -> Dict[str, Dict[str, Any]]:
    """Tool name -> metrics, from the run's ToolResult list."""
    mapping: Dict[str, Dict[str, Any]] = {}
    for result in results or []:
        name = str(getattr(result, "tool_name", "") or "")
        metrics = getattr(result, "metrics", None)
        if name and isinstance(metrics, dict):
            mapping[name] = metrics
    return mapping


def _spatial_gene_block(payload: Dict[str, Any], metrics_by_tool: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The spatial-gene result, from wherever this run put it.

    The descriptive lane stores it under `descriptive_analysis`; a validated run
    also writes a top-level tool result. Either is the same computation, and a
    table writer that knew only one of them would silently emit nothing for half
    the runs.
    """
    # The tool result first: the payload copies keep only the top 15 rows for the
    # report, so reading the payload gave a 15-row "per-gene" table for a 296-gene
    # panel. The ToolResult carries the full set.
    live = (metrics_by_tool or {}).get("spatial_variable_genes") or {}
    if live.get("top_genes"):
        return live
    descriptive = (payload.get("descriptive_analysis") or {}).get("spatial_genes") or {}
    if descriptive.get("top_genes"):
        return descriptive
    source = payload.get("spatial_variable_genes") or {}
    metrics = source.get("metrics") or source
    return metrics if metrics.get("top_genes") else {}


def _gene_rows(payload: Dict[str, Any], metrics_by_tool: Dict[str, Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """Every gene the spatial test saw, not only the ones that survived the screen.

    The screen ranks by analytic Moran's I and permutes only the top slice, so a
    reader who sees only the survivors cannot tell what was excluded or why. The
    untested genes carry their analytic I with `tested=false` and no p-value,
    which is exactly what is known about them.
    """
    spatial = _spatial_gene_block(payload, metrics_by_tool)
    if not spatial:
        return []
    screening = spatial.get("screening") or {}
    detected_by_gene = spatial.get("detected_by_gene") or {}
    scope = "tested set (%s of %s detected genes)" % (
        screening.get("tested_genes", "?"), screening.get("detected_genes", "?"))
    rows = []
    seen = set()
    for row in spatial.get("all_tested_genes") or spatial.get("top_genes") or []:
        gene = str((row or {}).get("gene") or "")
        if not gene or gene in seen:
            continue
        seen.add(gene)
        rows.append({
            "gene": gene,
            "morans_i": row.get("morans_i"),
            "pval_norm": row.get("pval_normality", row.get("pval_norm")),
            "pval_sim": row.get("pval_permutation", row.get("pval_sim")),
            "pval_adj": row.get("pval_adj"),
            "tested": "true",
            "detected_cells": row.get("detected_cells", detected_by_gene.get(gene, "")),
            "fdr_scope": scope,
            "screen_rule": screening.get("rule", ""),
        })
    for row in spatial.get("screened_out_genes") or []:
        gene = str((row or {}).get("gene") or "")
        if not gene or gene in seen:
            continue
        seen.add(gene)
        rows.append({
            "gene": gene,
            "morans_i": row.get("morans_i"),
            "pval_norm": "", "pval_sim": "", "pval_adj": "",
            "tested": "false",
            "detected_cells": row.get("detected_cells", ""),
            "fdr_scope": scope,
            "screen_rule": screening.get("rule", ""),
        })
    return rows


def _group_rows(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Moran's I per group, from both the gated and descriptive runs.

    `group_kind` distinguishes them, because a row about a reviewed cell type and
    a row about a Leiden cluster are different kinds of statement and would
    otherwise be indistinguishable once the table leaves the report.
    """
    rows = []
    for key, kind in (
        ("cell_type_spatial_autocorrelation", "cell_type"),
        ("cluster_spatial_autocorrelation", "cluster"),
    ):
        block = payload.get(key) or (payload.get("descriptive_analysis") or {}).get(key) or {}
        if block.get("status") != "computed":
            continue
        graph = block.get("graph") or {}
        for row in block.get("groups") or []:
            rows.append({
                "group": row.get("group"),
                "group_kind": kind,
                "morans_i": row.get("morans_i"),
                "pval_sim": row.get("pval_sim"),
                "pval_adj": row.get("pval_adj"),
                "n_cells": row.get("n_cells"),
                "graph_family": graph.get("family"),
                "n_neighs": graph.get("n_neighs"),
                "interpretation": row.get("interpretation"),
            })
    return rows


def _pair_rows(payload: Dict[str, Any], metrics_by_tool: Dict[str, Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    relationships = {
        str(item.get("pair")): item
        for item in ((payload.get("spatial_relationships") or {}).get("relationships") or [])
        if isinstance(item, dict)
    }
    counts = payload.get("cell_type_counts") or {}
    rows = []
    metrics = (
        metrics_by_tool.get("cell_neighborhood_enrichment")
        or metrics_by_tool.get("neighborhood_enrichment")
        or ((payload.get("descriptive_analysis") or {}).get("cluster_neighborhood") or {})
    )
    # `all_pairs` is every tested pair, self-pairs included. Appending
    # `self_pairs` on top of it wrote each self-pair twice -- and a duplicated row
    # in a results table is worse than a missing one, because nothing about it
    # looks wrong. Only fall back to the split lists when the full set is absent.
    pairs = list(metrics.get("all_pairs") or [])
    if not pairs:
        pairs = list(metrics.get("top_pairs") or []) + list(metrics.get("self_pairs") or [])
    seen_pairs = set()
    for item in pairs:
        if not isinstance(item, dict):
            continue
        label = str(item.get("pair") or "")
        parts = [part.strip() for part in label.split("|")]
        if len(parts) != 2 or label in seen_pairs:
            continue
        seen_pairs.add(label)
        extra = relationships.get(label, {})
        rows.append({
            "type_a": parts[0],
            "type_b": parts[1],
            "zscore": item.get("zscore"),
            "is_self_pair": "true" if parts[0] == parts[1] else "false",
            "n_a": counts.get(parts[0], ""),
            "n_b": counts.get(parts[1], ""),
            "tested_pair_count": metrics.get("tested_pair_count", ""),
            "graph_family": metrics.get("graph_family", "knn"),
            "evidence_status": extra.get("evidence_status", ""),
            "allowed_interpretation": extra.get("allowed_interpretation", ""),
        })
    return rows


def _marker_rows(payload: Dict[str, Any], metrics_by_tool: Dict[str, Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """Markers from the tool result where available, so the table carries the
    statistics; the descriptive payload keeps only the gene names."""
    rows = []
    live = (metrics_by_tool.get("marker_detection") or {}).get("markers_by_group") or {}
    for group, entries in live.items():
        for rank, entry in enumerate(entries or [], start=1):
            if not isinstance(entry, dict):
                continue
            rows.append({
                "group": str(group), "group_kind": "cell_type",
                "gene": str(entry.get("gene") or ""), "rank": rank,
                "marker_evidence": entry.get("logfoldchange", entry.get("score", "")),
            })
    descriptive = payload.get("descriptive_analysis") or {}
    for group, genes in (descriptive.get("markers_by_cluster") or {}).items():
        for rank, gene in enumerate(genes or [], start=1):
            rows.append({
                "group": str(group), "group_kind": "cluster",
                "gene": str(gene), "rank": rank,
                "marker_evidence": (descriptive.get("marker_lineage_calls") or {}).get(str(group), ""),
            })
    return rows


def _region_rows(payload: Dict[str, Any], metrics_by_tool: Dict[str, Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    metrics = metrics_by_tool.get("region_summary") or {}
    regions = metrics.get("regions") or {}
    # `regions` is a mapping of name -> summary, not a list. Iterating it as a
    # list yielded the region names as strings and no rows at all, so the table
    # silently did not exist.
    entries = (
        [(str(name), value) for name, value in regions.items()]
        if isinstance(regions, dict)
        else [(str((item or {}).get("region") or ""), item) for item in regions]
    )
    rows = []
    for name, region in entries:
        if not isinstance(region, dict):
            continue
        composition = region.get("cell_type_counts") or region.get("composition") or {}
        total = sum(int(value) for value in composition.values()) if composition else 0
        for cell_type, count in composition.items():
            rows.append({
                "region": name, "cell_type": str(cell_type), "n_cells": int(count),
                "fraction": round(int(count) / total, 4) if total else "",
                "region_total": total,
            })
    return rows


def _point_pattern_rows(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    block = payload.get("cell_type_point_pattern") or {}
    if block.get("status") != "computed":
        return []
    return [{
        "group": row.get("group"),
        "n_cells": row.get("n_cells"),
        "peak_deviation": row.get("peak_deviation"),
        "peak_radius_um": row.get("peak_radius_um"),
        "mean_deviation": row.get("mean_deviation"),
        "radii_above_envelope": row.get("radii_above_envelope"),
        "radii_below_envelope": row.get("radii_below_envelope"),
        "deviation_sign_varies": row.get("deviation_sign_varies"),
        "verdict": row.get("verdict"),
        "max_distance_um": block.get("max_distance_um"),
    } for row in block.get("groups") or []]


def _gene_pair_rows(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    block = payload.get("gene_pair_spatial_correlation") or {}
    if block.get("status") != "computed":
        return []
    return [{
        "gene_a": row.get("gene_a"), "gene_b": row.get("gene_b"),
        "lees_l": row.get("lees_l"), "pearson_r": row.get("pearson_r"),
        "status": row.get("status"), "interpretation": row.get("interpretation", ""),
    } for row in block.get("pairs") or []]


def _write_cells(
    payload: Dict[str, Any],
    dataset: SpatialDataset,
    tables_dir: Path,
    header: List[str],
) -> Optional[Dict[str, Any]]:
    """One row per cell: coordinates, grouping, region, QC, and LISA classes.

    The column that needs care is the label. On a gate-blocked run `cell_type`
    holds the loader's conservative marker-rule guesses, which the report is
    careful to describe as display-only -- and a spreadsheet column headed
    `cell_type` says the opposite to anyone who opens it without the report.
    """
    gate_open = str(payload.get("status") or "") == "validated_ready"
    label_column = "cell_type" if gate_open else "cell_type_provisional"
    label_report = payload.get("label_report") or {}
    review_method = str(label_report.get("method") or "loader_marker_rule")
    # Which classes the reviewer actually supplied. A partially reviewed section
    # leaves the loader's marker guess on every cell review did not reach, and
    # stamping `expert_label_table` on all of them -- which is what a single
    # table-wide source string did -- says the reviewer labelled cells they never
    # saw. The one column downstream code would use to filter was the one lying.
    reviewed = {str(name) for name in (label_report.get("reviewed_labels") or [])}

    clusters = (dataset.metadata or {}).get("cluster_assignments") or {}
    lisa = ((payload.get("descriptive_analysis") or {}).get("local_spatial_structure") or {})
    per_cell = lisa.get("per_cell") or {}
    lisa_columns: List[str] = []
    for row in lisa.get("genes") or []:
        gene = str(row.get("gene") or "")
        if row.get("status") == "computed" and gene:
            lisa_columns.extend(["lisa_%s" % gene, "lisa_%s_i" % gene, "lisa_%s_padj" % gene])

    region_candidates = ((payload.get("descriptive_analysis") or {}).get("region_proposal") or {})
    domain_of = (region_candidates.get("assignments") or {}).get("spatial_domain") or {}
    hotspot_of = (region_candidates.get("assignments") or {}).get("lisa_hotspot") or {}

    columns = (["cell_id", "x", "y", "cluster", label_column, "label_source", "region",
                "candidate_domain", "candidate_hotspot", "total_counts", "n_genes"]
               + lisa_columns)
    rows = []
    for index, record in enumerate(dataset.records):
        cell_id = record.cell_id or str(index)
        genes = record.raw_genes or record.genes or {}
        row = {
            "cell_id": cell_id,
            "x": round(float(record.x), 4),
            "y": round(float(record.y), 4),
            "cluster": clusters.get(cell_id, ""),
            label_column: record.cell_type or "",
            "label_source": (
                "" if not record.cell_type
                else review_method if (not reviewed or record.cell_type in reviewed)
                else "loader_marker_rule"
            ),
            "region": record.region or "",
            "candidate_domain": domain_of.get(cell_id, ""),
            "candidate_hotspot": hotspot_of.get(cell_id, ""),
            "total_counts": genes.get("TRANSCRIPT_COUNTS", genes.get("TOTAL_COUNTS", "")),
            # Measured genes detected in this cell. The exclusion is control
            # probes and QC pseudo-features -- not "uppercase keys", which was the
            # first attempt and excluded every real gene, since Xenium symbols are
            # uppercase. Every cell reported n_genes = 0.
            "n_genes": sum(
                1 for key, value in genes.items()
                if _positive(value)
                and key.upper() not in NON_EXPRESSION_FEATURE_NAMES
                and not is_control_feature(key)
            ),
        }
        for column in lisa_columns:
            row[column] = (per_cell.get(cell_id) or {}).get(column, "")
        rows.append(row)

    name = "cells.tsv.gz" if len(rows) > GZIP_ROW_THRESHOLD else "cells.tsv"
    path = tables_dir / name
    note = list(header)
    if not gate_open:
        note.append(
            "# WARNING: the gate is not open for this run, so the label column is named "
            "cell_type_provisional and holds the loader's marker-rule guesses, not expert labels."
        )
    _write_tsv(path, columns, rows, note)
    return {"table": name, "path": str(path), "rows": len(rows), "label_column": label_column}


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _provenance_header(payload: Dict[str, Any], run_id: str) -> List[str]:
    scope = payload.get("analysis_scope") or {}
    evidence = payload.get("gate_evidence") or {}
    lines = [
        "# SpatialMind result table",
        "# run_id\t%s" % (run_id or "unknown"),
        "# dataset\t%s" % (payload.get("dataset_path") or "unknown"),
        "# created_at\t%s" % (payload.get("created_at") or ""),
        "# gate_status\t%s" % (payload.get("status") or "unknown"),
        "# analysis_scope\t%s (%s of %s cells)" % (
            scope.get("scope", "unknown"), scope.get("loaded_records", "?"), scope.get("total_records", "?")),
        "# measured_genes\t%s" % (payload.get("features_loaded", "?")),
    ]
    if evidence.get("label_coverage") is not None:
        lines.append("# label_coverage\t%.4f (gate threshold %.2f)"
                     % (float(evidence["label_coverage"]), float(evidence.get("min_label_coverage") or 0.0)))
    if str(payload.get("status") or "") != "validated_ready":
        lines.append("# NOTE\tThe validation gate did not open for this run. No row in this file "
                     "supports a validated biological claim.")
    return lines


def _write_tsv(path: Path, columns: Sequence[str], rows: Sequence[Dict[str, Any]], header: Sequence[str]) -> None:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "wt", newline="", encoding="utf-8") as handle:
        for line in header:
            handle.write(line + "\n")
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write("\t".join(_cell(row.get(column, "")) for column in columns) + "\n")


def _cell(value: Any) -> str:
    """Tabs and newlines would break the format; nothing else needs escaping."""
    if value is None:
        return ""
    text = str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
