"""
Tests for the fetch_radiologist_findings tool.

The tool reads a JSON report broker indexed by DICOM accession and runs the
ACR classifier on the report text. We mock the classifier to avoid hitting
Gemini in the test suite (the real LLM path is covered by the `llm`-marked
tests in test_classifier.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from critcom.classification.classifier import ACRCategory, ClassificationResult
from critcom.tools.fetch_radiologist_findings import run


@pytest.fixture
def findings_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the tool at a clean temp dir for each test."""
    monkeypatch.setenv("CRITCOM_FINDINGS_DIR", str(tmp_path))
    return tmp_path


def _write_findings(dir_: Path, accession: str, **overrides) -> Path:
    payload = {
        "accession_number": accession,
        "patient_dicom_id": "TEST123",
        "signed_at": "2026-05-06T22:30:00+00:00",
        "radiologist": "synthetic-radiologist",
        "report_text": "Massive saddle pulmonary embolism with right heart strain.",
        "ordering_practitioner_id": "practitioner-001",
        "service_request_id": "sr-001",
        "patient_id": "patient-001",
    }
    payload.update(overrides)
    path = dir_ / f"{accession}.json"
    path.write_text(json.dumps(payload))
    return path


def _mock_classifier(category: ACRCategory, confidence: float = 0.95):
    """Return a context manager that swaps RadiologyClassifier with a mock."""
    result = ClassificationResult(
        category=category,
        finding="Mocked finding",
        reasoning="Mocked reasoning",
        confidence=confidence,
    )
    cls = AsyncMock()
    cls.classify = AsyncMock(return_value=result)
    return patch(
        "critcom.classification.classifier.RadiologyClassifier",
        return_value=cls,
    )


# ---------------------------------------------------------------------------
# Required-arg validation
# ---------------------------------------------------------------------------

class TestArguments:
    async def test_missing_accession_returns_error(self, findings_dir):
        r = await run({})
        assert r["found"] is False
        assert "required" in r["error"].lower()

    async def test_blank_accession_returns_error(self, findings_dir):
        r = await run({"accession_number": ""})
        assert r["found"] is False


# ---------------------------------------------------------------------------
# File-not-found path
# ---------------------------------------------------------------------------

class TestNotFound:
    async def test_unknown_accession_returns_not_found(self, findings_dir):
        r = await run({"accession_number": "doesnotexist"})
        assert r["found"] is False
        assert "doesnotexist" in r["error"]
        assert r["accession_number"] == "doesnotexist"

    async def test_invalid_json_returns_error(self, findings_dir):
        (findings_dir / "BAD.json").write_text("{not valid json")
        r = await run({"accession_number": "BAD"})
        assert r["found"] is False
        assert "JSON" in r["error"]


# ---------------------------------------------------------------------------
# Found path — classifier integration
# ---------------------------------------------------------------------------

class TestFoundPath:
    async def test_returns_payload_fields(self, findings_dir):
        _write_findings(findings_dir, "00007")
        with _mock_classifier(ACRCategory.CAT1):
            r = await run({"accession_number": "00007"})
        assert r["found"] is True
        assert r["accession_number"] == "00007"
        assert r["patient_dicom_id"] == "TEST123"
        assert r["service_request_id"] == "sr-001"
        assert r["patient_id"] == "patient-001"
        assert r["ordering_practitioner_id"] == "practitioner-001"
        assert r["report_text"]

    async def test_runs_classifier_and_fills_acr_category(self, findings_dir):
        _write_findings(findings_dir, "00007")
        with _mock_classifier(ACRCategory.CAT1, confidence=0.92):
            r = await run({"accession_number": "00007"})
        assert r["acr_category"] == "Cat1"
        assert r["classification"]["source"] == "llm"
        assert r["classification"]["confidence"] == 0.92
        assert "reasoning" in r["classification"]

    async def test_cat3_classifier_path(self, findings_dir):
        _write_findings(
            findings_dir,
            "00001",
            report_text="Stable cholelithiasis. No acute findings.",
        )
        with _mock_classifier(ACRCategory.CAT3):
            r = await run({"accession_number": "00001"})
        assert r["found"] is True
        assert r["acr_category"] == "Cat3"
        assert r["classification"]["source"] == "llm"


# ---------------------------------------------------------------------------
# Error / degraded paths
# ---------------------------------------------------------------------------

class TestDegraded:
    async def test_empty_report_text_skips_classifier(self, findings_dir):
        _write_findings(findings_dir, "00007", report_text="")
        # Even without mocking the classifier — it must not be invoked.
        r = await run({"accession_number": "00007"})
        assert r["found"] is True
        assert r["acr_category"] is None
        assert r["classification"]["source"] == "missing"

    async def test_classifier_exception_returns_missing_source(self, findings_dir):
        _write_findings(findings_dir, "00007")
        cls = AsyncMock()
        cls.classify = AsyncMock(side_effect=RuntimeError("Gemini quota exhausted"))
        with patch(
            "critcom.classification.classifier.RadiologyClassifier",
            return_value=cls,
        ):
            r = await run({"accession_number": "00007"})
        assert r["found"] is True
        assert r["acr_category"] is None
        assert r["classification"]["source"] == "missing"
        assert "quota" in r["classification"]["error"].lower()


# ---------------------------------------------------------------------------
# CRITCOM_FINDINGS_DIR override
# ---------------------------------------------------------------------------

class TestEnvOverride:
    async def test_findings_dir_env_var_is_respected(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom-broker"
        custom.mkdir()
        _write_findings(custom, "ABC123")
        monkeypatch.setenv("CRITCOM_FINDINGS_DIR", str(custom))
        with _mock_classifier(ACRCategory.CAT1):
            r = await run({"accession_number": "ABC123"})
        assert r["found"] is True
        assert r["accession_number"] == "ABC123"
