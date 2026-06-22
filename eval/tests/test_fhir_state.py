"""Tests for eval.fhir_state — direct HAPI state verification (httpx + respx)."""

from __future__ import annotations

import httpx
import respx
from httpx import Response

from eval import fhir_state

BASE = "http://hapi/fhir"


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "type": "searchset",
            "entry": [{"resource": r} for r in resources]}


_COMM = {"resourceType": "Communication", "id": "comm-1"}
_TASK_60 = {
    "resourceType": "Task",
    "id": "task-1",
    "restriction": {"period": {
        "start": "2026-01-01T00:00:00+00:00",
        "end": "2026-01-01T01:00:00+00:00",
    }},
}


@respx.mock
def test_present_with_deadline():
    respx.get(f"{BASE}/Communication").mock(return_value=Response(200, json=_bundle(_COMM)))
    respx.get(f"{BASE}/Task").mock(return_value=Response(200, json=_bundle(_TASK_60)))

    fs = fhir_state.check_state(BASE, "sr-001")
    assert fs.reachable is True
    assert fs.communication_present is True
    assert fs.task_present is True
    assert fs.task_deadline_minutes == 60


@respx.mock
def test_absent_when_no_communications():
    respx.get(f"{BASE}/Communication").mock(return_value=Response(200, json=_bundle()))

    fs = fhir_state.check_state(BASE, "sr-404")
    assert fs.reachable is True
    assert fs.communication_present is False
    assert fs.task_present is False
    assert fs.task_deadline_minutes is None


@respx.mock
def test_unreachable_returns_not_reachable():
    respx.get(f"{BASE}/Communication").mock(side_effect=httpx.ConnectError("down"))

    fs = fhir_state.check_state(BASE, "sr-001")
    assert fs.reachable is False
    assert fs.communication_present is False
    assert fs.task_present is False


@respx.mock
def test_http_error_returns_not_reachable():
    respx.get(f"{BASE}/Communication").mock(return_value=Response(500, text="boom"))

    fs = fhir_state.check_state(BASE, "sr-001")
    assert fs.reachable is False


def test_deadline_minutes_pure():
    assert fhir_state._deadline_minutes(_TASK_60) == 60
    assert fhir_state._deadline_minutes({}) is None
    assert fhir_state._deadline_minutes({"restriction": {"period": {"start": "x", "end": "y"}}}) is None
