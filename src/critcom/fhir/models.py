"""
Pydantic models for FHIR R4 resources used by CritCom.

Only the fields CritCom actually reads/writes are modelled — not the full spec.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class Coding(BaseModel):
    system: str | None = None
    code: str | None = None
    display: str | None = None


class CodeableConcept(BaseModel):
    coding: list[Coding] = Field(default_factory=list)
    text: str | None = None


class Reference(BaseModel):
    reference: str | None = None  # e.g. "Practitioner/123"
    display: str | None = None


class ContactPoint(BaseModel):
    system: str | None = None   # phone | fax | email | pager | url | sms | other
    value: str | None = None
    use: str | None = None      # home | work | temp | old | mobile


class HumanName(BaseModel):
    use: str | None = None
    family: str | None = None
    given: list[str] = Field(default_factory=list)

    @property
    def display(self) -> str:
        parts = self.given + ([self.family] if self.family else [])
        return " ".join(parts)


class Period(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class Meta(BaseModel):
    versionId: str | None = None
    lastUpdated: datetime | None = None


# ---------------------------------------------------------------------------
# Task status / intent
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    DRAFT = "draft"
    REQUESTED = "requested"
    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    READY = "ready"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in-progress"
    ON_HOLD = "on-hold"
    FAILED = "failed"
    COMPLETED = "completed"
    ENTERED_IN_ERROR = "entered-in-error"


class CommunicationStatus(str, Enum):
    PREPARATION = "preparation"
    IN_PROGRESS = "in-progress"
    NOT_DONE = "not-done"
    ON_HOLD = "on-hold"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ENTERED_IN_ERROR = "entered-in-error"
    UNKNOWN = "unknown"


class ServiceRequestStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on-hold"
    REVOKED = "revoked"
    COMPLETED = "completed"
    ENTERED_IN_ERROR = "entered-in-error"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Practitioner / PractitionerRole
# ---------------------------------------------------------------------------


class Practitioner(BaseModel):
    resourceType: str = "Practitioner"
    id: str | None = None
    meta: Meta | None = None
    name: list[HumanName] = Field(default_factory=list)
    telecom: list[ContactPoint] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name[0].display
        return f"Practitioner/{self.id}"

    def contact(self, system: str) -> str | None:
        """Return first contact value for the given system (e.g. 'phone')."""
        for cp in self.telecom:
            if cp.system == system and cp.value:
                return cp.value
        return None


class PractitionerRole(BaseModel):
    resourceType: str = "PractitionerRole"
    id: str | None = None
    meta: Meta | None = None
    active: bool = True
    period: Period | None = None
    practitioner: Reference | None = None
    organization: Reference | None = None
    code: list[CodeableConcept] = Field(default_factory=list)
    telecom: list[ContactPoint] = Field(default_factory=list)

    def contact(self, system: str) -> str | None:
        for cp in self.telecom:
            if cp.system == system and cp.value:
                return cp.value
        return None


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------


class Patient(BaseModel):
    resourceType: str = "Patient"
    id: str | None = None
    meta: Meta | None = None
    name: list[HumanName] = Field(default_factory=list)
    birthDate: str | None = None
    gender: str | None = None

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name[0].display
        return f"Patient/{self.id}"


# ---------------------------------------------------------------------------
# ServiceRequest
# ---------------------------------------------------------------------------


class ServiceRequest(BaseModel):
    resourceType: str = "ServiceRequest"
    id: str | None = None
    meta: Meta | None = None
    status: ServiceRequestStatus = ServiceRequestStatus.ACTIVE
    intent: str = "order"
    priority: str = "routine"   # routine | urgent | asap | stat
    code: CodeableConcept | None = None
    subject: Reference | None = None          # → Patient
    requester: Reference | None = None        # → Practitioner / PractitionerRole
    performer: list[Reference] = Field(default_factory=list)
    reasonCode: list[CodeableConcept] = Field(default_factory=list)
    note: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# DiagnosticReport
# ---------------------------------------------------------------------------


class DiagnosticReportStatus(str, Enum):
    REGISTERED = "registered"
    PARTIAL = "partial"
    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"
    CORRECTED = "corrected"
    APPENDED = "appended"
    CANCELLED = "cancelled"
    ENTERED_IN_ERROR = "entered-in-error"
    UNKNOWN = "unknown"


class Extension(BaseModel):
    url: str
    valueString: str | None = None
    valueCode: str | None = None


class DiagnosticReport(BaseModel):
    resourceType: str = "DiagnosticReport"
    id: str | None = None
    meta: Meta | None = None
    status: DiagnosticReportStatus = DiagnosticReportStatus.FINAL
    code: CodeableConcept | None = None
    subject: Reference | None = None              # → Patient
    basedOn: list[Reference] = Field(default_factory=list)   # → ServiceRequest
    issued: datetime | None = None
    performer: list[Reference] = Field(default_factory=list)
    conclusion: str | None = None
    presentedForm: list[dict[str, Any]] = Field(default_factory=list)
    extension: list[Extension] = Field(default_factory=list)

    ACR_CATEGORY_URL: str = "http://critcom/StructureDefinition/acr-category"

    @property
    def acr_category(self) -> str | None:
        """Returns Cat1, Cat2, Cat3, or None if extension is missing."""
        for ext in self.extension:
            if ext.url == self.ACR_CATEGORY_URL:
                return ext.valueCode or ext.valueString
        return None

    @property
    def service_request_id(self) -> str | None:
        for ref in self.basedOn:
            if ref.reference and ref.reference.startswith("ServiceRequest/"):
                return ref.reference.split("/", 1)[1]
        return None

    @property
    def patient_id(self) -> str | None:
        if self.subject and self.subject.reference and self.subject.reference.startswith("Patient/"):
            return self.subject.reference.split("/", 1)[1]
        return None


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------


class CommunicationPayload(BaseModel):
    contentString: str | None = None


class Communication(BaseModel):
    resourceType: str = "Communication"
    id: str | None = None
    meta: Meta | None = None
    status: CommunicationStatus = CommunicationStatus.IN_PROGRESS
    category: list[CodeableConcept] = Field(default_factory=list)
    subject: Reference | None = None          # → Patient
    # FHIR R4 distinguishes:
    #   basedOn: the request fulfilled by this communication (searchable as `based-on`)
    #   about:   topical references (NOT a default HAPI search parameter)
    # We populate both with the originating ServiceRequest so query_audit can
    # search by `based-on` and clients can also see the topical link.
    basedOn: list[Reference] = Field(default_factory=list)  # → ServiceRequest
    about: list[Reference] = Field(default_factory=list)    # → ServiceRequest
    recipient: list[Reference] = Field(default_factory=list)
    sender: Reference | None = None
    sent: datetime | None = None
    payload: list[CommunicationPayload] = Field(default_factory=list)
    note: list[dict[str, Any]] = Field(default_factory=list)

    # CritCom extension fields stored in note[0] as JSON for demo purposes
    # (a real system would use FHIR extensions)
    @property
    def finding_summary(self) -> str | None:
        if self.payload:
            return self.payload[0].contentString
        return None


# ---------------------------------------------------------------------------
# Task (acknowledgment tracker)
# ---------------------------------------------------------------------------


class TaskRestriction(BaseModel):
    repetitions: int | None = None
    period: Period | None = None
    recipient: list[Reference] = Field(default_factory=list)


class Task(BaseModel):
    resourceType: str = "Task"
    id: str | None = None
    meta: Meta | None = None
    status: TaskStatus = TaskStatus.REQUESTED
    intent: str = "order"
    priority: str = "routine"          # routine | urgent | asap | stat
    code: CodeableConcept | None = None
    focus: Reference | None = None     # → Communication
    for_: Reference | None = Field(default=None, alias="for")  # → Patient
    authoredOn: datetime | None = None
    lastModified: datetime | None = None
    requester: Reference | None = None
    owner: Reference | None = None     # → Practitioner expected to ack
    restriction: TaskRestriction | None = None
    note: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# FHIR Bundle (used for search results)
# ---------------------------------------------------------------------------


class BundleEntry(BaseModel):
    fullUrl: str | None = None
    resource: dict[str, Any] | None = None


class Bundle(BaseModel):
    resourceType: str = "Bundle"
    id: str | None = None
    type: str = "searchset"
    total: int = 0
    entry: list[BundleEntry] = Field(default_factory=list)
