import os
from typing import List, Optional

from ..algorithms import AlgorithmEngine
from ..ingestion import DataIngestionLayer, available_samples
from ..llm import LLMProvider
from ..memory import MemoryLayer
from ..planner import LLMReasoningLayer
from ..schemas import AgentRun, ToolResult
from ..storage import StorageLayer
from ..viz import VisualizationLayer


class SpatialMindAgent:
    """Coordinates the six layers into one agent run."""

    def __init__(
        self,
        output_root: str = "outputs",
        memory_root: str = ".spatialmind",
        llm_provider: Optional[LLMProvider] = None,
    ) -> None:
        self.ingestion = DataIngestionLayer()
        self.algorithms = AlgorithmEngine()
        self.reasoning = LLMReasoningLayer(llm_provider=llm_provider)
        self.visualization = VisualizationLayer()
        self.storage = StorageLayer(output_root)
        self.memory = MemoryLayer(memory_root)

    def run(self, prompt: str, data_path: str) -> AgentRun:
        plan = self.reasoning.plan(prompt)
        sample_id = plan.request.sample_id or available_samples(data_path)[0]
        dataset = self.ingestion.load(data_path, sample_id=sample_id)
        similar_runs = self.memory.recall(prompt, sample_id)
        run_info = self.storage.start_run(dataset.sample_id)
        run_id = run_info["run_id"]
        run_dir = run_info["run_dir"]

        self.storage.write_json(run_dir, "execution_plan.json", plan)

        results: List[ToolResult] = []
        for step in plan.steps:
            result = self.algorithms.run(step.tool, dataset, step.parameters)
            results.append(result)
            self.storage.write_json(run_dir, "%s.json" % step.tool, result)

        svg_path = self.visualization.render_distribution_svg(dataset, run_dir, plan.request.cell_types)
        report_path = self.visualization.render_report(dataset, prompt, results, run_dir, svg_path, similar_runs)
        interactive_path = os.path.join(run_dir, "spatial_distribution_interactive.html")
        provenance_path = self.storage.write_provenance(
            run_dir,
            {
                "run_id": run_id,
                "sample_id": dataset.sample_id,
                "source_path": dataset.source_path,
                "sources": dataset.sources,
                "ingestion_qc_metrics": dataset.qc_metrics,
                "ingestion_processing_steps": dataset.processing_steps,
                "normalized": dataset.normalized,
                "prompt": prompt,
                "tools": [step.tool for step in plan.steps],
                "artifacts": {
                    "report": report_path,
                    "spatial_distribution": svg_path,
                    "interactive_spatial_distribution": interactive_path,
                },
            },
        )

        summary = " ".join(result.summary for result in results)
        self.memory.remember(run_id, dataset.sample_id, prompt, summary, report_path)
        return AgentRun(
            run_id=run_id,
            plan=plan,
            results=results,
            report_path=report_path,
            provenance_path=provenance_path,
        )
