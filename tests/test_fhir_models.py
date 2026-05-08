"""
Tests for FHIR Pydantic models.
"""

from __future__ import annotations

import pytest
from critcom.fhir.models import (
    Bundle,
    Communication,
    CommunicationStatus,
    ContactPoint,
    HumanName,
    Patient,
    Practitioner,
    PractitionerRole,
    ServiceRequest,
    Task,
    TaskStatus,
)


class TestHumanName:
    def test_display_full(self):
        name = HumanName(family="Chen", given=["Michael", "Wei"])
        assert name.display == "Michael Wei Chen"

    def test_display_family_only(self):
        name = HumanName(family="Smith")
        assert name.display == "Smith"

    def test_display_no_name(self):
        name = HumanName()
        assert name.display == ""


class TestPractitioner:
    def test_display_name(self):
        p = Practitioner(
            id="prac-001",
            name=[HumanName(family="Patel", given=["Sunita"])],
        )
        assert p.display_name == "Sunita Patel"

    def test_display_name_fallback(self):
        p = Practitioner(id="prac-001")
        assert p.display_name == "Practitioner/prac-001"

    def test_contact(self):
        p = Practitioner(
            id="prac-001",
            telecom=[
                ContactPoint(system="phone", value="317-555-1001"),
                ContactPoint(system="pager", value="317-555-2001"),
            ],
        )
        assert p.contact("phone") == "317-555-1001"
        assert p.contact("pager") == "317-555-2001"
        assert p.contact("email") is None


class TestPractitionerRole:
    def test_on_call_detection(self):
        from critcom.fhir.models import CodeableConcept, Coding
        role = PractitionerRole(
            id="role-oncall-001",
            code=[CodeableConcept(coding=[Coding(system="http://critcom/role-type", code="on-call")])],
        )
        # The model itself doesn't filter — that's the client's job
        # But we can verify the code parses correctly
        assert role.code[0].coding[0].code == "on-call"


class TestCommunication:
    def test_finding_summary(self):
        from critcom.fhir.models import CommunicationPayload
        comm = Communication(
            payload=[CommunicationPayload(contentString="Large aortic dissection identified")]
        )
        assert comm.finding_summary == "Large aortic dissection identified"

    def test_finding_summary_empty(self):
        comm = Communication()
        assert comm.finding_summary is None


class TestTask:
    def test_status_enum(self):
        task = Task(status=TaskStatus.REQUESTED)
        assert task.status == TaskStatus.REQUESTED

    def test_for_alias(self):
        from critcom.fhir.models import Reference
        task = Task(**{"for": Reference(reference="Patient/patient-001")})
        assert task.for_ is not None
        assert task.for_.reference == "Patient/patient-001"

    def test_serialization_alias(self):
        from critcom.fhir.models import Reference
        task = Task(**{"for": Reference(reference="Patient/patient-001")})
        dumped = task.model_dump(by_alias=True)
        assert "for" in dumped
        assert dumped["for"]["reference"] == "Patient/patient-001"


class TestBundle:
    def test_empty_bundle(self):
        b = Bundle()
        assert b.total == 0
        assert b.entry == []

    def test_bundle_with_entries(self):
        from critcom.fhir.models import BundleEntry
        b = Bundle(
            total=1,
            entry=[BundleEntry(resource={"resourceType": "Patient", "id": "p1"})]
        )
        assert b.total == 1
        assert b.entry[0].resource["id"] == "p1"
