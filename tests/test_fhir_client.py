"""
Tests for FHIRClient — all HTTP calls are intercepted by respx.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from critcom.fhir.client import FHIRClient, FHIRError
from critcom.fhir.models import (
    Communication,
    CommunicationPayload,
    CommunicationStatus,
    Practitioner,
    ServiceRequest,
    Task,
    TaskStatus,
)

BASE_URL = "http://localhost:8080/fhir"


@pytest.fixture
def client():
    return FHIRClient(base_url=BASE_URL)


# ---------------------------------------------------------------------------
# Practitioner
# ---------------------------------------------------------------------------

PRACTITIONER_FIXTURE = {
    "resourceType": "Practitioner",
    "id": "practitioner-001",
    "name": [{"use": "official", "family": "Chen", "given": ["Michael", "Wei"]}],
    "telecom": [
        {"system": "phone", "value": "317-555-1001", "use": "work"},
        {"system": "pager", "value": "317-555-2001", "use": "work"},
    ],
}

SERVICE_REQUEST_FIXTURE = {
    "resourceType": "ServiceRequest",
    "id": "sr-001",
    "status": "active",
    "intent": "order",
    "subject": {"reference": "Patient/patient-001"},
    "requester": {"reference": "Practitioner/practitioner-001", "display": "Dr. Michael Chen"},
}

COMMUNICATION_FIXTURE = {
    "resourceType": "Communication",
    "id": "comm-001",
    "status": "in-progress",
    "sent": "2026-04-25T14:32:00+00:00",
    "payload": [{"contentString": "Type A aortic dissection identified"}],
}

TASK_FIXTURE = {
    "resourceType": "Task",
    "id": "task-001",
    "status": "requested",
    "intent": "order",
    "priority": "stat",
}


class TestGetPractitioner:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self, client):
        respx.get(f"{BASE_URL}/Practitioner/practitioner-001").mock(
            return_value=Response(200, json=PRACTITIONER_FIXTURE)
        )
        prac = await client.get_practitioner("practitioner-001")
        assert prac.id == "practitioner-001"
        assert prac.display_name == "Michael Wei Chen"
        assert prac.contact("phone") == "317-555-1001"

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_found(self, client):
        respx.get(f"{BASE_URL}/Practitioner/missing").mock(
            return_value=Response(404, json={"resourceType": "OperationOutcome"})
        )
        with pytest.raises(FHIRError) as exc_info:
            await client.get_practitioner("missing")
        assert exc_info.value.status_code == 404


class TestGetServiceRequest:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self, client):
        respx.get(f"{BASE_URL}/ServiceRequest/sr-001").mock(
            return_value=Response(200, json=SERVICE_REQUEST_FIXTURE)
        )
        sr = await client.get_service_request("sr-001")
        assert sr.id == "sr-001"
        assert sr.requester.reference == "Practitioner/practitioner-001"


class TestCreateCommunication:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self, client):
        respx.post(f"{BASE_URL}/Communication").mock(
            return_value=Response(201, json=COMMUNICATION_FIXTURE)
        )
        comm = Communication(
            payload=[CommunicationPayload(contentString="Critical finding")]
        )
        created = await client.create_communication(comm)
        assert created.id == "comm-001"
        assert created.finding_summary == "Type A aortic dissection identified"


class TestTaskOperations:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_task(self, client):
        respx.get(f"{BASE_URL}/Task/task-001").mock(
            return_value=Response(200, json=TASK_FIXTURE)
        )
        task = await client.get_task("task-001")
        assert task.id == "task-001"
        assert task.status == TaskStatus.REQUESTED

    @pytest.mark.asyncio
    @respx.mock
    async def test_update_task_status(self, client):
        completed = {**TASK_FIXTURE, "status": "completed"}
        respx.get(f"{BASE_URL}/Task/task-001").mock(return_value=Response(200, json=TASK_FIXTURE))
        respx.put(f"{BASE_URL}/Task/task-001").mock(return_value=Response(200, json=completed))

        task = await client.update_task_status("task-001", TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED


class TestFHIRError:
    def test_error_message(self):
        err = FHIRError(404, "Resource not found")
        assert "404" in str(err)
        assert "Resource not found" in str(err)


# ---------------------------------------------------------------------------
# search_audit — by ServiceRequest and by Patient
# ---------------------------------------------------------------------------

def _bundle(*resources: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": r} for r in resources],
    }


_COMM = {
    "resourceType": "Communication",
    "id": "comm-1",
    "status": "in-progress",
    "subject": {"reference": "Patient/patient-002"},
    "payload": [{"contentString": "Subsegmental PE"}],
}
_TASK = {"resourceType": "Task", "id": "task-1", "status": "requested"}


class TestSearchAudit:
    @pytest.mark.asyncio
    @respx.mock
    async def test_by_service_request_uses_based_on(self, client):
        comm_route = respx.get(
            f"{BASE_URL}/Communication", params={"based-on": "ServiceRequest/sr-002"}
        ).mock(return_value=Response(200, json=_bundle(_COMM)))
        respx.get(f"{BASE_URL}/Task").mock(return_value=Response(200, json=_bundle(_TASK)))

        audit = await client.search_audit(service_request_id="sr-002")
        assert comm_route.called
        assert len(audit["communications"]) == 1
        assert len(audit["tasks"]) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_by_patient_uses_subject(self, client):
        comm_route = respx.get(
            f"{BASE_URL}/Communication", params={"subject": "Patient/patient-002"}
        ).mock(return_value=Response(200, json=_bundle(_COMM)))
        respx.get(f"{BASE_URL}/Task").mock(return_value=Response(200, json=_bundle(_TASK)))

        audit = await client.search_audit(patient_id="patient-002")
        assert comm_route.called
        assert len(audit["communications"]) == 1
        assert len(audit["tasks"]) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_identifiers_returns_empty(self, client):
        audit = await client.search_audit()
        assert audit == {"communications": [], "tasks": []}


# ---------------------------------------------------------------------------
# from_env — per-request context beats env, and clears (no stale token bleed)
# ---------------------------------------------------------------------------

class TestFromEnvContext:
    @pytest.fixture(autouse=True)
    def _clear_context(self):
        from critcom.fhir import context
        context.set_fhir_context(fhir_url=None, fhir_token=None)
        yield
        context.set_fhir_context(fhir_url=None, fhir_token=None)

    @pytest.mark.asyncio
    async def test_context_overrides_env(self, monkeypatch):
        from critcom.fhir import context
        from critcom.fhir.client import FHIRClient

        monkeypatch.setenv("CRITCOM_FHIR_BASE_URL", "http://default/fhir")
        context.set_fhir_context(fhir_url="http://tenant-a/fhir", fhir_token="tok-a")
        async with FHIRClient.from_env() as c:
            assert c._base_url == "http://tenant-a/fhir"
            assert c._client.headers.get("Authorization") == "Bearer tok-a"

    @pytest.mark.asyncio
    async def test_cleared_context_falls_back_to_env_without_stale_token(self, monkeypatch):
        from critcom.fhir import context
        from critcom.fhir.client import FHIRClient

        monkeypatch.setenv("CRITCOM_FHIR_BASE_URL", "http://default/fhir")
        monkeypatch.delenv("CRITCOM_FHIR_BEARER_TOKEN", raising=False)
        context.set_fhir_context(fhir_url=None, fhir_token=None)
        async with FHIRClient.from_env() as c:
            assert c._base_url == "http://default/fhir"
            assert "Authorization" not in c._client.headers
