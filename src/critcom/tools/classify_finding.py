"""
MCP Tool: classify_finding

Accepts a radiology report text and returns an ACR classification.
"""

from __future__ import annotations

from typing import Any

import structlog

from critcom.classification.classifier import RadiologyClassifier

log = structlog.get_logger(__name__)

_classifier: RadiologyClassifier | None = None


def _get_classifier() -> RadiologyClassifier:
    global _classifier
    if _classifier is None:
        _classifier = RadiologyClassifier()
    return _classifier


TOOL_DEFINITION = {
    "name": "classify_finding",
    "description": (
        "Classify a radiology report text against ACR critical-results categories. "
        "Returns category (Cat1/Cat2/Cat3/None), the key finding, reasoning, and confidence."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "report_text": {
                "type": "string",
                "description": "Full text of the radiology report to classify.",
            }
        },
        "required": ["report_text"],
    },
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    report_text: str = arguments["report_text"]
    log.info("tool.classify_finding", chars=len(report_text))

    result = await _get_classifier().classify(report_text)

    return {
        "category": result.category.value,
        "finding": result.finding,
        "reasoning": result.reasoning,
        "confidence": result.confidence,
        "is_critical": result.is_critical,
        "ack_timeout_minutes": result.ack_timeout_minutes,
        "escalation_levels": result.escalation_levels,
    }
