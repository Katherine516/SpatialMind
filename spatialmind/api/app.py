from pathlib import Path
from typing import Dict, Literal

from dataclasses import asdict, is_dataclass

from ..agent import SpatialAgent, SpatialMindAgent
from ..batch import BatchEngine
from ..llm import build_llm_provider
from ..ingestion import validate_xenium_label_intake
from ..pilot import run_pilot
from ..promotion import build_local_promotion_report
from ..storage import StorageLayer
from ..viz import QCGate


def create_app():
    """Create an optional FastAPI app when FastAPI is installed."""

    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("Install fastapi and pydantic to enable the API layer.") from exc

    class RunRequest(BaseModel):
        prompt: str
        data_path: str = "data/demo_spatial.csv"
        output_root: str = "outputs"
        llm_provider: str = "local"
        llm_model: str = ""
        qc_approved: bool = False
        report_format: Literal["html", "pdf", "both"] = "html"

    class BatchRequest(BaseModel):
        query: str
        dataset_ids: list[str]

    class XeniumPilotRequest(BaseModel):
        data_path: str = "data/Human_Breast_Biomarkers_S1_Top_outs"
        output_dir: str = "outputs/xenium_validated_pilot"
        max_records: int = 2500
        min_label_coverage: float = 0.7
        min_region_coverage: float = 0.7
        allow_single_region: bool = False
        report_format: Literal["html", "pdf", "both"] = "html"

    class LocalPromotionRequest(BaseModel):
        data_root: str = "data"
        output_root: str = "outputs/agent_promotion"
        max_records: int = 800

    app = FastAPI(title="SpatialMind")
    qc_gate = QCGate()
    batch_engine = BatchEngine()

    @app.get("/health")
    def health() -> Dict[str, object]:
        return {"status": "ok", "service": "spatialmind"}

    @app.post("/runs")
    def create_run(request: RunRequest) -> Dict[str, object]:
        provider = build_llm_provider(request.llm_provider, model=request.llm_model)
        agent = SpatialMindAgent(output_root=request.output_root, llm_provider=provider)
        run = agent.run(request.prompt, request.data_path, report_format=request.report_format)
        return {
            "run_id": run.run_id,
            "report_path": run.report_path,
            "report_paths": run.report_paths,
            "provenance_path": run.provenance_path,
            "results": [result.summary for result in run.results],
        }

    @app.post("/sessions/{session_id}/query")
    def query_session(session_id: str, request: RunRequest) -> Dict[str, object]:
        if not (request.qc_approved or qc_gate.is_approved(session_id)):
            raise HTTPException(status_code=403, detail="QC must be approved before analysis.")
        response = SpatialAgent().run(request.prompt, request.data_path, session_id=session_id)
        return _jsonable(response)

    @app.post("/sessions/{session_id}/approve-qc")
    def approve_qc(session_id: str) -> Dict[str, object]:
        qc_gate.approve(session_id)
        return {"session_id": session_id, "qc_approved": True}

    @app.post("/batch/jobs")
    def create_batch_job(request: BatchRequest) -> Dict[str, object]:
        return _jsonable(batch_engine.submit(request.query, request.dataset_ids))

    @app.get("/batch/jobs/{job_id}/status")
    def get_batch_status(job_id: str) -> Dict[str, object]:
        return _jsonable(batch_engine.get(job_id))

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> Dict[str, object]:
        return _jsonable(StorageLayer().get_run(run_id))

    @app.get("/runs/{run_id}/figures")
    def list_run_figures(run_id: str) -> Dict[str, object]:
        return {"run_id": run_id, "figures": StorageLayer().list_figures(run_id)}

    @app.post("/pilot/xenium/intake")
    def validate_xenium_intake(request: XeniumPilotRequest) -> Dict[str, object]:
        return _jsonable(
            validate_xenium_label_intake(
                request.data_path,
                max_records=request.max_records,
                min_label_coverage=request.min_label_coverage,
                min_region_coverage=request.min_region_coverage,
                allow_single_region=request.allow_single_region,
                report_format=request.report_format,
            )
        )

    @app.post("/pilot/xenium/run")
    def run_xenium_pilot(request: XeniumPilotRequest) -> Dict[str, object]:
        return _jsonable(
            run_pilot(
                request.data_path,
                output_dir=Path(request.output_dir),
                max_records=request.max_records,
                min_label_coverage=request.min_label_coverage,
                min_region_coverage=request.min_region_coverage,
                allow_single_region=request.allow_single_region,
            )
        )

    @app.post("/promotion/local")
    def promote_local(request: LocalPromotionRequest) -> Dict[str, object]:
        return _jsonable(build_local_promotion_report(request.data_root, request.output_root, max_records=request.max_records))

    return app


def _jsonable(value):
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
