"""
Tests for the ACR radiology classifier.

The `llm` marker makes real API calls — excluded from default pytest runs.
The other tests mock the Anthropic client.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from critcom.classification.classifier import ACRCategory, ClassificationResult, RadiologyClassifier
from critcom.classification.prompts import build_user_message, SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Prompt tests (no LLM needed)
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_build_user_message_includes_report(self):
        report = "There is a large intracranial hemorrhage."
        msg = build_user_message(report)
        assert report in msg

    def test_system_prompt_covers_all_categories(self):
        for cat in ["Cat1", "Cat2", "Cat3", "None"]:
            assert cat in SYSTEM_PROMPT or cat.lower() in SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_acr(self):
        assert "ACR" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# ClassificationResult tests
# ---------------------------------------------------------------------------

class TestClassificationResult:
    def test_cat1_is_critical(self):
        r = ClassificationResult(
            category=ACRCategory.CAT1,
            finding="Aortic dissection",
            reasoning="Life-threatening",
            confidence=0.98,
        )
        assert r.is_critical is True

    def test_cat2_is_critical(self):
        r = ClassificationResult(
            category=ACRCategory.CAT2,
            finding="Pulmonary embolism",
            reasoning="Urgent",
            confidence=0.92,
        )
        assert r.is_critical is True

    def test_cat3_not_critical(self):
        r = ClassificationResult(
            category=ACRCategory.CAT3,
            finding="Degenerative changes",
            reasoning="Routine",
            confidence=0.95,
        )
        assert r.is_critical is False

    def test_none_not_critical(self):
        r = ClassificationResult(
            category=ACRCategory.NONE,
            finding="No critical finding",
            reasoning="Normal study",
            confidence=0.99,
        )
        assert r.is_critical is False

    def test_cat1_timeout(self, monkeypatch):
        monkeypatch.setenv("CRITCOM_CAT1_ACK_TIMEOUT_MINUTES", "60")
        r = ClassificationResult(category=ACRCategory.CAT1, finding="x", reasoning="x", confidence=0.9)
        assert r.ack_timeout_minutes == 60

    def test_cat2_timeout(self, monkeypatch):
        monkeypatch.setenv("CRITCOM_CAT2_ACK_TIMEOUT_MINUTES", "1440")
        r = ClassificationResult(category=ACRCategory.CAT2, finding="x", reasoning="x", confidence=0.9)
        assert r.ack_timeout_minutes == 1440

    def test_none_no_timeout(self):
        r = ClassificationResult(category=ACRCategory.NONE, finding="x", reasoning="x", confidence=0.9)
        assert r.ack_timeout_minutes is None


# ---------------------------------------------------------------------------
# Classifier unit tests (mocked LLM)
# ---------------------------------------------------------------------------

def _make_mock_response(category: str, finding: str, confidence: float = 0.95) -> MagicMock:
    payload = {
        "category": category,
        "finding": finding,
        "reasoning": "Test reasoning.",
        "confidence": confidence,
    }
    content_block = MagicMock()
    content_block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [content_block]
    return response


@pytest.fixture
def mock_anthropic():
    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock()
    return mock_client


class TestRadiologyClassifier:
    @pytest.mark.asyncio
    async def test_classify_cat1(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            "Cat1", "Large aortic dissection extending from the root to the celiac axis"
        )
        classifier = RadiologyClassifier(client=mock_anthropic)
        result = await classifier.classify("CT chest report text here.")

        assert result.category == ACRCategory.CAT1
        assert result.is_critical is True
        assert "aortic dissection" in result.finding.lower()

    @pytest.mark.asyncio
    async def test_classify_cat2(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            "Cat2", "Acute pulmonary embolism in right lower lobe segmental branches", 0.91
        )
        classifier = RadiologyClassifier(client=mock_anthropic)
        result = await classifier.classify("CT pulmonary angiography report.")

        assert result.category == ACRCategory.CAT2
        assert result.is_critical is True

    @pytest.mark.asyncio
    async def test_classify_none(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            "None", "No critical finding", 0.99
        )
        classifier = RadiologyClassifier(client=mock_anthropic)
        result = await classifier.classify("Normal chest X-ray.")

        assert result.category == ACRCategory.NONE
        assert result.is_critical is False
        assert result.ack_timeout_minutes is None

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self, mock_anthropic):
        payload = {"category": "Cat1", "finding": "Test", "reasoning": "Test", "confidence": 0.9}
        content_block = MagicMock()
        content_block.text = f"```json\n{json.dumps(payload)}\n```"
        response = MagicMock()
        response.content = [content_block]
        mock_anthropic.messages.create.return_value = response

        classifier = RadiologyClassifier(client=mock_anthropic)
        result = await classifier.classify("Report text.")
        assert result.category == ACRCategory.CAT1


# ---------------------------------------------------------------------------
# Real LLM tests (skipped by default — run with: pytest -m llm)
# ---------------------------------------------------------------------------

@pytest.mark.llm
class TestClassifierWithRealLLM:
    @pytest.mark.asyncio
    async def test_aortic_dissection_is_cat1(self):
        import pathlib, json
        fixtures = pathlib.Path(__file__).parent / "fixtures" / "reports" / "sample_reports.json"
        reports = json.loads(fixtures.read_text())
        report_text = reports["cat1_aortic_dissection"]["text"]

        classifier = RadiologyClassifier()
        result = await classifier.classify(report_text)
        assert result.category == ACRCategory.CAT1
        assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_normal_cxr_is_none(self):
        import pathlib, json
        fixtures = pathlib.Path(__file__).parent / "fixtures" / "reports" / "sample_reports.json"
        reports = json.loads(fixtures.read_text())
        report_text = reports["none_normal_cxr"]["text"]

        classifier = RadiologyClassifier()
        result = await classifier.classify(report_text)
        assert result.category == ACRCategory.NONE
