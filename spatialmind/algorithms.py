import math
import random
from collections import Counter, defaultdict
from typing import Callable, Dict, Iterable, List, Tuple

from .schemas import SpatialDataset, ToolResult


ToolFn = Callable[[SpatialDataset, Dict[str, object]], ToolResult]


class AlgorithmEngine:
    """Typed registry of agent-callable analysis tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolFn] = {
            "cell_type_distribution": self.cell_type_distribution,
            "spatial_gene_expression": self.spatial_gene_expression,
            "cell_type_colocalization": self.cell_type_colocalization,
        }

    def run(self, tool_name: str, dataset: SpatialDataset, parameters: Dict[str, object]) -> ToolResult:
        if tool_name not in self._tools:
            raise KeyError("Unknown algorithm tool: %s" % tool_name)
        return self._tools[tool_name](dataset, parameters)

    def cell_type_distribution(self, dataset: SpatialDataset, parameters: Dict[str, object]) -> ToolResult:
        requested = [str(value) for value in parameters.get("cell_types", [])]
        records = _filter_cell_types(dataset.records, requested)
        counts = Counter(record.cell_type for record in records)
        centroids = {}
        for cell_type in counts:
            selected = [record for record in records if record.cell_type == cell_type]
            centroids[cell_type] = {
                "x": round(sum(record.x for record in selected) / len(selected), 3),
                "y": round(sum(record.y for record in selected) / len(selected), 3),
            }
        summary = "Mapped %d observations across %d cell types." % (len(records), len(counts))
        return ToolResult(
            tool_name="cell_type_distribution",
            summary=summary,
            metrics={
                "counts": dict(counts),
                "centroids": centroids,
                "cell_types": sorted(counts.keys()),
            },
            caveats=list(dataset.notes),
        )

    def spatial_gene_expression(self, dataset: SpatialDataset, parameters: Dict[str, object]) -> ToolResult:
        requested = [str(value).upper() for value in parameters.get("genes", [])]
        if not requested:
            requested = dataset.genes[:3]
        metrics = {}
        caveats = list(dataset.notes)
        for gene in requested:
            values = [record.genes.get(gene, 0.0) for record in dataset.records]
            if gene not in dataset.genes:
                caveats.append("Gene %s was not found; values are reported as zero." % gene)
            metrics[gene] = {
                "mean": round(_mean(values), 4),
                "max": round(max(values) if values else 0.0, 4),
                "positive_observations": sum(1 for value in values if value > 0),
            }
        return ToolResult(
            tool_name="spatial_gene_expression",
            summary="Summarized spatial expression for %d genes." % len(requested),
            metrics=metrics,
            caveats=caveats,
        )

    def cell_type_colocalization(self, dataset: SpatialDataset, parameters: Dict[str, object]) -> ToolResult:
        requested = [str(value) for value in parameters.get("cell_types", [])]
        if len(requested) < 2:
            requested = dataset.cell_types[:2]
        if len(requested) < 2:
            return ToolResult(
                tool_name="cell_type_colocalization",
                summary="Co-localization requires at least two cell types.",
                caveats=list(dataset.notes) + ["Provide at least two cell types."],
            )

        first, second = requested[0], requested[1]
        bin_size = float(parameters.get("bin_size", 20.0))
        first_density = _density_by_bin(dataset, first, bin_size)
        second_density = _density_by_bin(dataset, second, bin_size)
        bins = sorted(set(first_density.keys()) | set(second_density.keys()))
        x_values = [first_density.get(item, 0.0) for item in bins]
        y_values = [second_density.get(item, 0.0) for item in bins]
        correlation = _pearson(x_values, y_values)
        p_value = _permutation_p_value(x_values, y_values, observed=correlation)
        interpretation = _interpret_colocalization(correlation, p_value, first, second)

        return ToolResult(
            tool_name="cell_type_colocalization",
            summary=interpretation,
            metrics={
                "cell_type_a": first,
                "cell_type_b": second,
                "grid_bin_size": bin_size,
                "pearson_r": round(correlation, 4),
                "permutation_p_value": round(p_value, 4),
                "occupied_bins": len(bins),
            },
            caveats=list(dataset.notes) + [
                "This prototype uses binned density correlation; production analysis should choose a null model based on assay resolution."
            ],
        )


def _filter_cell_types(records: Iterable[object], requested: List[str]) -> List[object]:
    if not requested:
        return list(records)
    requested_lower = {item.lower() for item in requested}
    return [record for record in records if record.cell_type.lower() in requested_lower]


def _density_by_bin(dataset: SpatialDataset, cell_type: str, bin_size: float) -> Dict[Tuple[int, int], float]:
    density: Dict[Tuple[int, int], float] = defaultdict(float)
    for record in dataset.records:
        if record.cell_type.lower() != cell_type.lower():
            continue
        key = (int(record.x // bin_size), int(record.y // bin_size))
        density[key] += 1.0
    return density


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pearson(x_values: List[float], y_values: List[float]) -> float:
    if len(x_values) != len(y_values) or not x_values:
        return 0.0
    x_mean = _mean(x_values)
    y_mean = _mean(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    x_var = sum((x - x_mean) ** 2 for x in x_values)
    y_var = sum((y - y_mean) ** 2 for y in y_values)
    denominator = math.sqrt(x_var * y_var)
    return numerator / denominator if denominator else 0.0


def _permutation_p_value(x_values: List[float], y_values: List[float], observed: float, rounds: int = 499) -> float:
    if not x_values or not y_values:
        return 1.0
    rng = random.Random(7)
    more_extreme = 0
    shuffled = list(y_values)
    for _ in range(rounds):
        rng.shuffle(shuffled)
        candidate = _pearson(x_values, shuffled)
        if abs(candidate) >= abs(observed):
            more_extreme += 1
    return (more_extreme + 1) / float(rounds + 1)


def _interpret_colocalization(correlation: float, p_value: float, first: str, second: str) -> str:
    if p_value < 0.05 and correlation > 0:
        return "%s and %s show positive spatial co-localization." % (first, second)
    if p_value < 0.05 and correlation < 0:
        return "%s and %s show spatial segregation." % (first, second)
    return "%s and %s do not show significant co-localization in this prototype test." % (first, second)
