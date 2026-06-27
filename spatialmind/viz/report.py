import html
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from spatialmind.contracts import MethodCitation


@dataclass
class ReportPaths:
    html: str
    pdf: str = ""


class ReportBuilder:
    """Structured v2 HTML report builder with PDF-ready interface."""

    def build(
        self,
        response: Any,
        output_dir: str,
        format: str = "html",
        citations: Optional[Dict[str, MethodCitation]] = None,
    ) -> ReportPaths:
        os.makedirs(output_dir, exist_ok=True)
        html_path = os.path.join(output_dir, "structured_report.html")
        sections = [
            ("Executive Summary", self._summary(response)),
            ("Data Quality", "QC dashboard and ingestion warnings are linked from run artifacts when available."),
            ("Methods", self._methods(response, citations or {})),
            ("Results", self._results(response)),
            ("Limitations", self._limitations(response)),
            ("Figures Gallery", "Generated figures are stored with the run and referenced in provenance."),
            ("Statistical Summary", self._stats(response)),
            ("Appendix: Provenance", "Full tool trace, parameters, software versions, and provenance hash are stored in provenance.json."),
        ]
        body = "\n".join("<section><h2>%s</h2><p>%s</p></section>" % (title, html.escape(content)) for title, content in sections)
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write("<!doctype html><html><head><meta charset='utf-8'><title>SpatialMind Report</title></head><body>%s</body></html>" % body)
        pdf_path = ""
        if format in {"pdf", "both"}:
            pdf_path = os.path.join(output_dir, "structured_report.pdf")
            with open(pdf_path, "w", encoding="utf-8") as handle:
                handle.write("PDF export requires WeasyPrint in the production environment. Source HTML: %s\n" % html_path)
        return ReportPaths(html=html_path, pdf=pdf_path)

    def _summary(self, response: Any) -> str:
        return str(getattr(response, "interpretation", "") or "Structured report generated from available tool results.")

    def _methods(self, response: Any, citations: Dict[str, MethodCitation]) -> str:
        tools = [getattr(call, "tool_name", "") for call in getattr(response, "tool_trace", [])]
        lines = []
        for tool in tools:
            citation = citations.get(tool)
            if citation is None:
                lines.append(tool)
                continue
            version = " v%s" % citation.software_version if citation.software_version else ""
            paper = " (%s)" % citation.paper_citation if citation.paper_citation else ""
            lines.append("%s%s%s" % (citation.method_name, version, paper))
        return "Methods used: %s." % ("; ".join(line for line in lines if line) or "not available")

    def _results(self, response: Any) -> str:
        summaries: List[str] = []
        for call in getattr(response, "tool_trace", []):
            result = getattr(call, "result", None)
            if result is not None:
                summaries.append(getattr(result, "summary", ""))
        return " ".join(item for item in summaries if item) or "No result summaries available."

    def _stats(self, response: Any) -> str:
        return "Statistics are available in individual tool JSON outputs."

    def _limitations(self, response: Any) -> str:
        facts = self._run_facts(response)
        lines = []
        if facts["has_transfer"]:
            confidence = facts["mean_transfer_confidence"]
            suffix = " (mean confidence %.2f)" % confidence if confidence is not None else ""
            lines.append("Cell-type labels on the target were transferred from a reference%s; they are predictions, not direct measurements." % suffix)
            if facts["low_confidence_cell_count"]:
                lines.append("%d cells fell below the confidence threshold and were flagged, not assigned." % facts["low_confidence_cell_count"])
            lines.append("Reference and target were aligned over shared features only.")
        if facts["has_targeted_panel"]:
            lines.append("Xenium uses a targeted panel; absence of a gene means it was not measured, not that it is unexpressed.")
        if facts["has_gene_activity"]:
            lines.append("Accessibility-derived gene activity is an estimate of expression, not measured transcription.")
        if not facts["ran_deconvolution"]:
            lines.append("No deconvolution was run.")
        if not facts["ran_ligand_receptor"]:
            lines.append("No ligand-receptor inference was run.")
        if not facts["ran_pathway"]:
            lines.append("No pathway inference was run.")
        lines.append("No causal or mechanistic conclusion is supported by this analysis.")
        return " ".join(lines)

    def _run_facts(self, response: Any) -> Dict[str, Any]:
        facts: Dict[str, Any] = {
            "has_transfer": False,
            "has_targeted_panel": False,
            "has_gene_activity": False,
            "ran_deconvolution": False,
            "ran_ligand_receptor": False,
            "ran_pathway": False,
            "mean_transfer_confidence": None,
            "low_confidence_cell_count": 0,
        }
        for call in getattr(response, "tool_trace", []):
            tool_name = getattr(call, "tool_name", "")
            result = getattr(call, "result", None)
            if tool_name in {"spatial_deconvolution"}:
                facts["ran_deconvolution"] = True
            if tool_name in {"ligand_receptor_analysis", "spatial_communication_flow"}:
                facts["ran_ligand_receptor"] = True
            if tool_name in {"pathway_activity"}:
                facts["ran_pathway"] = True
            if result is None:
                continue
            metrics = getattr(result, "metrics", {}) or {}
            caveats = " ".join(getattr(result, "caveats", []) or [])
            if tool_name == "reference_label_transfer":
                facts["has_transfer"] = True
                facts["mean_transfer_confidence"] = metrics.get("mean_transfer_confidence")
                facts["low_confidence_cell_count"] = int(metrics.get("low_confidence_cell_count") or 0)
            if metrics.get("feature_type") == "gene_activity" or "accessibility-inferred" in caveats:
                facts["has_gene_activity"] = True
            if metrics.get("feature_type") == "targeted_panel" or "targeted panel" in caveats:
                facts["has_targeted_panel"] = True
        return facts
