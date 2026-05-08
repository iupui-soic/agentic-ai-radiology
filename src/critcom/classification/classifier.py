"""
ACR critical-results classifier (Gemini-backed).

Reads a radiology report's free text and returns a structured
ClassificationResult with the inferred ACR category.

This module reuses the same Gemini key the agent uses (GOOGLE_API_KEY).
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from critcom.classification.prompts import SYSTEM_PROMPT, build_user_message

log = structlog.get_logger(__name__)


class ACRCategory(str, Enum):
    CAT1 = "Cat1"   # Immediate  — contact within 60 min
    CAT2 = "Cat2"   # Urgent     — contact within 24 h
    CAT3 = "Cat3"   # Routine    — normal workflow
    NONE = "None"   # No critical finding


class ClassificationResult(BaseModel):
    category: ACRCategory
    finding: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def is_critical(self) -> bool:
        return self.category in (ACRCategory.CAT1, ACRCategory.CAT2)

    @property
    def ack_timeout_minutes(self) -> int | None:
        timeouts = {
            ACRCategory.CAT1: int(os.getenv("CRITCOM_CAT1_ACK_TIMEOUT_MINUTES", "60")),
            ACRCategory.CAT2: int(os.getenv("CRITCOM_CAT2_ACK_TIMEOUT_MINUTES", "1440")),
        }
        return timeouts.get(self.category)

    @property
    def escalation_levels(self) -> int:
        levels = {
            ACRCategory.CAT1: int(os.getenv("CRITCOM_CAT1_ESCALATION_LEVELS", "2")),
            ACRCategory.CAT2: int(os.getenv("CRITCOM_CAT2_ESCALATION_LEVELS", "1")),
        }
        return levels.get(self.category, 0)


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


class RadiologyClassifier:
    """Classifies radiology report text using Google Gemini.

    Reuses GOOGLE_API_KEY and CRITCOM_LLM_MODEL — the same values the agent uses.
    """

    def __init__(self, api_key: str | None = None) -> None:
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai is required. Install with: pip install google-generativeai"
            ) from e

        key = api_key or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        genai.configure(api_key=key)

        self._genai = genai
        self._model_name = os.getenv("CRITCOM_LLM_MODEL", "gemini-2.0-flash")
        self._temperature = float(os.getenv("CRITCOM_LLM_TEMPERATURE", "0.0"))
        self._max_tokens = int(os.getenv("CRITCOM_LLM_MAX_TOKENS", "1024"))

    async def classify(self, report_text: str) -> ClassificationResult:
        """Classify a radiology report and return a structured result."""
        log.info("classifier.start", chars=len(report_text), model=self._model_name)

        model = self._genai.GenerativeModel(
            self._model_name,
            system_instruction=SYSTEM_PROMPT,
            generation_config={
                "temperature": self._temperature,
                "max_output_tokens": self._max_tokens,
                "response_mime_type": "application/json",
            },
        )

        response = await model.generate_content_async(build_user_message(report_text))

        raw = (response.text or "").strip()
        log.debug("classifier.raw_response", raw=raw[:300])

        cleaned = _strip_fences(raw)
        parsed: dict[str, Any] = json.loads(cleaned)
        result = ClassificationResult.model_validate(parsed)

        log.info(
            "classifier.done",
            category=result.category,
            finding=result.finding[:80],
            confidence=result.confidence,
        )
        return result
