import os
from typing import List, Optional

from ..ingestion import DataIngestionLayer, available_samples
from ..llm import LLMProvider
from ..memory import MemoryLayer
from ..planner import LLMReasoningLayer
from ..schemas import AgentRun, ToolResult, ExecutionStep
from ..contracts import ToolCallSpec
from ..tools import build_default_registry
from .runtime import execute_tool_step, check_execution_gate, require_valid_tool_plan, effective_tool_call
from ..storage import StorageLayer
from ..viz import VisualizationLayer


class SpatialMindAgent:
    """Compatibility intent parser with canonical, policy-enforced execution.

    The v1 intent vocabulary remains for saved requests; AlgorithmEngine is no
    longer an execution backend. New plan construction belongs to agent.planning.
    """

    def __init__(
        self,
        output_root: str = "outputs",
        memory_root: str = ".spatialmind",
        llm_provider: Optional[LLMProvider] = None,
    ) -> None:
        self.ingestion = DataIngestionLayer()
        self.registry = build_default_registry()
        self.reasoning = LLMReasoningLayer(llm_provider=llm_provider)
        self.visualization = VisualizationLayer()
        self.storage = StorageLayer(output_root)
        self.memory = MemoryLayer(memory_root)

    def run(self, prompt: str, data_path: str, report_format: str = "html", expression_semantics: str = "auto") -> AgentRun:
        plan = self.reasoning.plan(prompt)
        sample_id = plan.request.sample_id or available_samples(data_path)[0]
        dataset = self.ingestion.load(data_path, sample_id=sample_id, expression_semantics=expression_semantics)
        # Retain v1 intent parsing for callers, but execute only canonical tools.
        effective_steps = []
        for step in plan.steps:
            if step.tool == "cell_type_distribution":
                effective_steps.append(ExecutionStep(step.name, "cell_type_annotation", {"method": "existing_labels"}))
            elif step.tool == "cell_type_colocalization":
                effective_steps.append(ExecutionStep(step.name, "cell_neighborhood_enrichment",
                                                    {"n_neighs": 6, "n_perms": 250, "random_state": 0},
                                                    depends_on=["annotation"]))
            elif step.tool == "spatial_gene_expression":
                for gene in step.parameters.get("genes") or dataset.genes[:3]:
                    effective_steps.append(ExecutionStep("Overlay " + gene, "feature_overlay", {"feature": gene}))
            else:
                raise ValueError("Unknown legacy intent: " + step.tool)
        plan.steps = effective_steps
        specs = [effective_tool_call(ToolCallSpec(step.tool, step.parameters,
                              requires=["annotation"] if step.tool == "cell_neighborhood_enrichment" else ["normalized_counts"]))
                 for step in plan.steps]
        for step, spec in zip(plan.steps, specs):
            step.parameters = spec.params
        require_valid_tool_plan(specs, ["normalized_counts"] if dataset.normalized else [],
                                [tool.name for tool in self.registry.list_plannable()])
        # `DataIngestionLayer.load` accepts a Xenium bundle, so this path could
        # run cell-type tools over a real section with no reviewed label in
        # sight. It now asks the same question every other path asks.
        gate_decision = check_execution_gate(data_path, specs, dataset=dataset)

        similar_runs = self.memory.recall(prompt, sample_id)
        run_info = self.storage.start_run(dataset.sample_id)
        run_id = run_info["run_id"]
        run_dir = run_info["run_dir"]

        self.storage.write_json(run_dir, "execution_plan.json", plan)

        results: List[ToolResult] = []
        for index, (step, spec) in enumerate(zip(plan.steps, specs)):
            result = execute_tool_step(dataset, spec, self.registry, data_path, gate_decision)
            if gate_decision.get("caveat"):
                result.caveats.append(gate_decision["caveat"])
            results.append(result)
            self.storage.write_json(run_dir, "%02d_%s.json" % (index + 1, step.tool), result)

        svg_path = self.visualization.render_distribution_svg(dataset, run_dir, plan.request.cell_types)
        report_paths = self.visualization.render_report(
            dataset,
            prompt,
            results,
            run_dir,
            svg_path,
            similar_runs,
            report_format=report_format,
        )
        report_path = report_paths.primary(report_format)
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
                "gate_decision": gate_decision,
                "execution_boundary": "agent.runtime.execute_tool_step",
                "effective_plan": specs,
                "artifacts": {
                    "report": report_path,
                    "reports": report_paths.to_dict(),
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
            report_paths=report_paths.to_dict(),
        )
