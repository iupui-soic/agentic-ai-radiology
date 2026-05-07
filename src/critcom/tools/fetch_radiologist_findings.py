"""
MCP Tool: fetch_radiologist_findings

Retrieves a radiologist's signed report text for a given DICOM accession from a
local "report broker" — modeled here as a directory of JSON files indexed by
accession number.

This deliberately separates worklist data (which is real, public DCMTK fixture
data and must stay pristine) from findings data (synthetic, written at sign-off
time, lives in a different system in real life). In production this stand-in
would be replaced by a DICOM Structured Report fetch, an HL7 ORU listener, or
a commit hook on the dictation system.

Pairs with fetch_report_dicom: the agent calls dicom first to confirm the study
exists and get patient/scheduling context, then calls this tool to get the
findings text, then runs the ACR classifier on that text.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import structlog

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "fetch_radiologist_findings",
    "description": (
        "Retrieve the radiologist-signed findings for a DICOM accession from the local "
        "report broker (post-sign-off, separate from the worklist). Use this after "
        "fetch_report_dicom when the worklist entry exists but you need the report "
        "text to classify."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "accession_number": {
                "type": "string",
                "description": "DICOM accession number from the worklist entry",
            },
        },
        "required": ["accession_number"],
    },
}


def _findings_dir() -> pathlib.Path:
    override = os.getenv("CRITCOM_FINDINGS_DIR")
    if override:
        return pathlib.Path(override)
    return pathlib.Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "dicom_findings"


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    accession = arguments.get("accession_number")
    log.info("tool.fetch_radiologist_findings", accession=accession)

    if not accession:
        return {"found": False, "error": "accession_number is required"}

    path = _findings_dir() / f"{accession}.json"
    if not path.exists():
        return {
            "found": False,
            "error": f"No signed findings on file for accession {accession}",
            "accession_number": accession,
        }

    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.exception("tool.fetch_radiologist_findings.parse_error")
        return {"found": False, "error": f"Findings file is not valid JSON: {e}"}

    report_text = payload.get("report_text")

    # Always classify via LLM — this branch has no FHIR tag to fall back on.
    classification: dict[str, Any] = {"source": "missing"}
    acr_category: str | None = None
    if report_text:
        try:
            from critcom.classification.classifier import RadiologyClassifier
            cls = await RadiologyClassifier().classify(report_text)
            acr_category = cls.category.value
            classification = {
                "source": "llm",
                "confidence": cls.confidence,
                "reasoning": cls.reasoning,
                "finding": cls.finding,
            }
            log.info(
                "tool.fetch_radiologist_findings.classified",
                accession=accession,
                category=acr_category,
                confidence=cls.confidence,
            )
        except Exception as e:
            log.warning("tool.fetch_radiologist_findings.classify_failed", error=str(e))
            classification = {"source": "missing", "error": str(e)}

    return {
        "found": True,
        "accession_number": payload.get("accession_number", accession),
        "patient_dicom_id": payload.get("patient_dicom_id"),
        "signed_at": payload.get("signed_at"),
        "radiologist": payload.get("radiologist"),
        "report_text": report_text,
        "ordering_practitioner_id": payload.get("ordering_practitioner_id"),
        "service_request_id": payload.get("service_request_id"),
        "patient_id": payload.get("patient_id"),
        "acr_category": acr_category,
        "classification": classification,
    }