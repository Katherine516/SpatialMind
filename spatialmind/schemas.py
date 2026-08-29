from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from spatialmind.contracts.metrics import QualityMetrics


# Per-cell measurements stored alongside genes that are NOT expression: library
# size and morphology proxies, plus the instrument's own background counts. They
# live on the record because they drive QC, and they must be excluded from every
# expression matrix -- left in, they are on a different scale and dominate PCA and
# marker ranking.
#
# Defined once here because three layers need the same answer (ingestion
# normalization, expression matrix construction, label evidence). Three separate
# copies drifted identical until a fourth feature was added, at which point they
# would not have.
NON_EXPRESSION_FEATURE_NAMES = frozenset(
    {
        "TRANSCRIPT_COUNTS",
        "TOTAL_COUNTS",
        "CELL_AREA",
        "NUCLEUS_AREA",
        # Xenium per-cell background, from cells.csv. The instrument's own
        # signal-to-noise measure for each cell.
        "CONTROL_PROBE_COUNTS",
        "CONTROL_CODEWORD_COUNTS",
        "UNASSIGNED_CODEWORD_COUNTS",
    }
)


@dataclass
class RawDataSource:
    path: str
    data_type: str
    modality: str
    sample_id: Optional[str] = None
    coordinate_system: str = "pixel"
    image_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpotRecord:
    sample_id: str
    x: float
    y: float
    cell_type: str
    genes: Dict[str, float]
    region: Optional[str] = None
    cell_id: Optional[str] = None
    # Immutable source values used for count-aware QC and reproducible exports.
    # ``genes`` is the analysis layer and may be normalized/log-transformed.
    raw_genes: Dict[str, float] = field(default_factory=dict)


@dataclass
class SpatialDataset:
    sample_id: str
    records: List[SpotRecord]
    source_path: str
    modality: str = "spatial_table"
    coordinate_system: str = "pixel"
    normalized: bool = False
    notes: List[str] = field(default_factory=list)
    sources: List[RawDataSource] = field(default_factory=list)
    qc_metrics: Dict[str, Any] = field(default_factory=dict)
    processing_steps: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def cell_types(self) -> List[str]:
        return sorted({record.cell_type for record in self.records})

    @property
    def genes(self) -> List[str]:
        names = set()
        for record in self.records:
            names.update(record.genes.keys())
        return sorted(names)

    def bounds(self) -> Dict[str, float]:
        xs = [record.x for record in self.records]
        ys = [record.y for record in self.records]
        return {
            "min_x": min(xs) if xs else 0.0,
            "max_x": max(xs) if xs else 0.0,
            "min_y": min(ys) if ys else 0.0,
            "max_y": max(ys) if ys else 0.0,
        }


@dataclass
class AnalysisRequest:
    raw_text: str
    sample_id: Optional[str] = None
    cell_types: List[str] = field(default_factory=list)
    genes: List[str] = field(default_factory=list)
    wants_visualization: bool = False
    wants_colocalization: bool = False
    wants_report: bool = True


@dataclass
class ExecutionStep:
    name: str
    tool: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    request: AnalysisRequest
    steps: List[ExecutionStep]
    clarifications: List[str] = field(default_factory=list)


@dataclass
class ToolResult:
    tool_name: str
    summary: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    quality_metrics: Optional[QualityMetrics] = None
    artifacts: Dict[str, str] = field(default_factory=dict)
    caveats: List[str] = field(default_factory=list)
    label_caveat: Optional[str] = None


@dataclass
class AgentRun:
    run_id: str
    plan: ExecutionPlan
    results: List[ToolResult]
    report_path: str
    provenance_path: str
    report_paths: Dict[str, str] = field(default_factory=dict)
