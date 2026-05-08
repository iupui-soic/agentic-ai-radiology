"""
MCP Tool: dispatch_communication

Creates a FHIR Communication resource representing the critical-result notification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from critcom.fhir.client import FHIRClient
from critcom.fhir.models import (
    CodeableConcept,
    Coding,
    Communication,
    CommunicationPayload,
    Reference,
)

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "dispatch_communication",
    "description": (
        "Create a FHIR Communication resource to record that a critical-result notification "
        "was dispatched to a provider. Returns the Communication resource ID."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service_request_id": {"type": "string", "description": "FHIR ServiceRequest ID"},
            "patient_id": {"type": "string", "description": "FHIR Patient ID"},
            "recipient_practitioner_id": {"type": "string", "description": "FHIR Practitioner ID of the recipient"},
            "acr_category": {"type": "string", "enum": ["Cat1", "Cat2", "Cat3", "None"]},
            "finding_summary": {"type": "string", "description": "One-sentence summary of the critical finding"},
        },
        "required": ["service_request_id", "patient_id", "recipient_practitioner_id", "acr_category", "finding_summary"],
    },
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    log.info("tool.dispatch_communication", **{k: v for k, v in arguments.items() if k != "finding_summary"})

    comm = Communication(
        status="in-progress",
        category=[
            CodeableConcept(
                coding=[Coding(system="http://critcom/acr-category", code=arguments["acr_category"])],
                text=arguments["acr_category"],
            )
        ],
        subject=Reference(reference=f"Patient/{arguments['patient_id']}"),
        basedOn=[Reference(reference=f"ServiceRequest/{arguments['service_request_id']}")],
        about=[Reference(reference=f"ServiceRequest/{arguments['service_request_id']}")],
        recipient=[Reference(reference=f"Practitioner/{arguments['recipient_practitioner_id']}")],
        sent=datetime.now(tz=timezone.utc),
        payload=[CommunicationPayload(contentString=arguments["finding_summary"])],
    )

    async with FHIRClient.from_env() as client:
        created = await client.create_communication(comm)

    return {
        "communication_id": created.id,
        "status": created.status.value,
        "sent": created.sent.isoformat() if created.sent else None,
    }
