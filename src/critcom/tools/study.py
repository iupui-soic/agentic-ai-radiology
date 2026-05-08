"""
Shared CritComStudy model — normalized representation of a study from any source.
"""

from __future__ import annotations

from pydantic import BaseModel


class CritComStudy(BaseModel):
    """Normalized study object emitted by both fetch_report_fhir and fetch_report_dicom."""

    source: str                     # "fhir" or "dicom"
    diagnostic_report_id: str | None = None
    service_request_id: str | None = None
    patient_id: str | None = None
    study_uid: str | None = None    # DICOM only
    accession_number: str | None = None

    priority: str = "routine"       # routine | urgent | stat
    acr_category: str | None = None  # Cat1 | Cat2 | Cat3 | None
    modality: str | None = None
    report_text: str | None = None
    impression: str | None = None
