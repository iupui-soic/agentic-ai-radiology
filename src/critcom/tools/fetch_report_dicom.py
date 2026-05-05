"""
MCP Tool: fetch_report_dicom

Queries a DICOM Modality Worklist (MWL) via C-FIND using pynetdicom and returns
a normalized CritComStudy. Used as a fallback when no FHIR DiagnosticReport is
available — for sites that have not adopted FHIR.

The DICOM source provides:
  - Patient ID / accession number / study UID
  - Requested Procedure Priority (STAT / HIGH / ROUTINE / MEDIUM)
  - Modality and study description

It does NOT provide free-text report content. CritCom relies on the radiologist
having marked the study completed in the worklist; the report itself, when
available, is fetched via FHIR (which the agent should do as a follow-up call
to fetch_report_fhir).
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from critcom.tools.study import CritComStudy

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "fetch_report_dicom",
    "description": (
        "Query a DICOM Modality Worklist (C-FIND) for a study by accession number or patient ID. "
        "Returns a normalized study object with priority, modality, and identifiers. "
        "Use this when no FHIR DiagnosticReport is available."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "accession_number": {"type": "string"},
            "patient_id": {"type": "string"},
        },
        "required": [],
    },
}


# Map DICOM Requested Procedure Priority to FHIR-style priority codes
_DICOM_PRIORITY_MAP = {
    "STAT": "stat",
    "HIGH": "urgent",
    "MEDIUM": "routine",
    "ROUTINE": "routine",
    "LOW": "routine",
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    accession = arguments.get("accession_number")
    patient_id = arguments.get("patient_id")

    log.info("tool.fetch_report_dicom", accession=accession, patient_id=patient_id)

    if not accession and not patient_id:
        return {"error": "Provide accession_number or patient_id", "found": False}

    try:
        from pydicom.dataset import Dataset
        from pynetdicom import AE
        from pynetdicom.sop_class import ModalityWorklistInformationFind
    except ImportError:
        return {
            "error": "pynetdicom is not installed. Install with: pip install pynetdicom",
            "found": False,
        }

    host = os.getenv("CRITCOM_DICOM_HOST", "localhost")
    port = int(os.getenv("CRITCOM_DICOM_PORT", "4242"))
    called_aet = os.getenv("CRITCOM_DICOM_AET", "ORTHANC")
    calling_aet = os.getenv("CRITCOM_DICOM_CALLING_AET", "CRITCOM")

    ae = AE(ae_title=calling_aet)
    ae.add_requested_context(ModalityWorklistInformationFind)

    query = Dataset()
    query.PatientName = ""
    query.PatientID = patient_id or ""
    query.AccessionNumber = accession or ""
    query.RequestedProcedurePriority = ""
    query.Modality = ""
    query.StudyInstanceUID = ""
    query.RequestedProcedureDescription = ""

    sps = Dataset()
    sps.ScheduledProcedureStepStartDate = ""
    sps.ScheduledProcedureStepStartTime = ""
    sps.ScheduledStationAETitle = ""
    sps.Modality = ""
    sps.ScheduledProcedureStepStatus = ""
    query.ScheduledProcedureStepSequence = [sps]

    matches: list[Dataset] = []
    try:
        assoc = ae.associate(host, port, ae_title=called_aet)
        if not assoc.is_established:
            return {"error": f"Could not associate with DICOM SCP {host}:{port}", "found": False}
        try:
            for status, identifier in assoc.send_c_find(query, ModalityWorklistInformationFind):
                if status and status.Status in (0xFF00, 0xFF01) and identifier:
                    matches.append(identifier)
        finally:
            assoc.release()
    except Exception as e:
        log.exception("tool.fetch_report_dicom.error")
        return {"error": f"DICOM query failed: {e}", "found": False}

    if not matches:
        return {"found": False, "error": "No matching worklist entries"}

    ds = matches[0]
    raw_priority = str(getattr(ds, "RequestedProcedurePriority", "") or "").upper()
    priority = _DICOM_PRIORITY_MAP.get(raw_priority, "routine")

    study = CritComStudy(
        source="dicom",
        patient_id=str(getattr(ds, "PatientID", "") or "") or None,
        study_uid=str(getattr(ds, "StudyInstanceUID", "") or "") or None,
        accession_number=str(getattr(ds, "AccessionNumber", "") or "") or None,
        priority=priority,
        modality=str(getattr(ds, "Modality", "") or "") or None,
        report_text=str(getattr(ds, "RequestedProcedureDescription", "") or "") or None,
    )

    return {"found": True, "study": study.model_dump(), "raw_priority": raw_priority, "match_count": len(matches)}
