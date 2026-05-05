"""
ACR critical-results classifier.

Calls Claude via the Anthropic SDK and returns a structured ClassificationResult.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any

import anthropic
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


class RadiologyClassifier:
    """Classifies radiology reports using Claude."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._client = client or anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        self._model = os.getenv("CRITCOM_LLM_MODEL", "claude-sonnet-4-5").replace("anthropic/", "")
        self._temperature = float(os.getenv("CRITCOM_LLM_TEMPERATURE", "0.0"))
        self._max_tokens = int(os.getenv("CRITCOM_LLM_MAX_TOKENS", "1024"))

    async def classify(self, report_text: str) -> ClassificationResult:
        """Classify a radiology report and return a structured result."""
        log.info("classifier.start", chars=len(report_text))

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(report_text)}],
        )

        raw = response.content[0].text.strip()
        log.debug("classifier.raw_response", raw=raw[:300])

        # Strip accidental markdown fences the model might add
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        parsed: dict[str, Any] = json.loads(raw)
        result = ClassificationResult.model_validate(parsed)

        log.info(
            "classifier.done",
            category=result.category,
            finding=result.finding,
            confidence=result.confidence,
        )
        return result
