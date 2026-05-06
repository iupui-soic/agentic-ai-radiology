"""
MCP Tool: fetch_report_fhir

Retrieves a signed DiagnosticReport from FHIR plus its linked ServiceRequest
to obtain priority. Returns a normalized CritComStudy.
"""

from __future__ import annotations

from typing import Any

import structlog

from critcom.fhir.client import FHIRClient
from critcom.tools.study import CritComStudy

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "fetch_report_fhir",
    "description": (
        "Retrieve a signed radiology DiagnosticReport from a FHIR R4 server, plus its linked "
        "ServiceRequest for priority. Returns the report text, ACR category, priority, and IDs. "
        "Pass either diagnostic_report_id (preferred) or service_request_id."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "diagnostic_report_id": {"type": "string", "description": "FHIR DiagnosticReport ID"},
            "service_request_id": {"type": "string", "description": "FHIR ServiceRequest ID (alternative lookup)"},
        },
        "required": [],
    },
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    dr_id: str | None = arguments.get("diagnostic_report_id")
    sr_id: str | None = arguments.get("service_request_id")

    log.info("tool.fetch_report_fhir", dr_id=dr_id, sr_id=sr_id)

    if not dr_id and not sr_id:
        return {"error": "Provide diagnostic_report_id or service_request_id", "found": False}

    async with FHIRClient.from_env() as client:
        if dr_id:
            report = await client.get_diagnostic_report(dr_id)
        else:
            reports = await client.search_diagnostic_reports(status="final", based_on=sr_id, limit=1)
            if not reports:
                return {"error": f"No final DiagnosticReport found for ServiceRequest/{sr_id}", "found": False}
            report = reports[0]

        priority = "routine"
        modality = None
        sr_id_resolved = report.service_request_id or sr_id
        if sr_id_resolved:
            try:
                sr = await client.get_service_request(sr_id_resolved)
                priority = sr.priority or "routine"
                if sr.code:
                    modality = sr.code.text
            except Exception as e:
                log.warning("tool.fetch_report_fhir.sr_lookup_failed", error=str(e))

    study = CritComStudy(
        source="fhir",
        diagnostic_report_id=report.id,
        service_request_id=sr_id_resolved,
        patient_id=report.patient_id,
        priority=priority,
        acr_category=report.acr_category,
        modality=modality,
        report_text=report.conclusion or _extract_presented_form_text(report),
        impression=report.conclusion,
    )

    # If the DiagnosticReport has no ACR tag, fall back to LLM inference.
    # Tag (when set by clinician/RIS) is always primary; LLM fills the gap.
    classification_meta: dict[str, Any] = {"source": "tag" if study.acr_category else "missing"}
    if not study.acr_category and study.report_text:
        try:
            from critcom.classification.classifier import RadiologyClassifier
            classifier = RadiologyClassifier()
            cls = await classifier.classify(study.report_text)
            study.acr_category = cls.category.value
            classification_meta = {
                "source": "llm",
                "confidence": cls.confidence,
                "reasoning": cls.reasoning,
                "finding": cls.finding,
            }
            log.info("tool.fetch_report_fhir.llm_inferred", category=cls.category.value, confidence=cls.confidence)
        except Exception as e:
            log.warning("tool.fetch_report_fhir.llm_classification_failed", error=str(e))
            classification_meta = {"source": "missing", "error": str(e)}

    result: dict[str, Any] = {"found": True, "study": study.model_dump()}
    result["classification"] = classification_meta
    return result


def _extract_presented_form_text(report: Any) -> str | None:
    """Pull the report text from presentedForm if conclusion is empty."""
    for pf in report.presentedForm or []:
        if pf.get("contentType", "").startswith("text/"):
            data = pf.get("data")
            if data:
                import base64
                try:
                    return base64.b64decode(data).decode("utf-8", errors="replace")
                except Exception:
                    return None
    return None
