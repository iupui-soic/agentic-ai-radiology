"""
MCP Tool: escalate

When an acknowledgment Task goes overdue, escalate to the next provider
(on-call backup) and dispatch a new Communication + Task.
"""

from __future__ import annotations

from typing import Any

import structlog

from critcom.fhir.client import FHIRClient
from critcom.fhir.models import TaskStatus

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "escalate",
    "description": (
        "Escalate an unacknowledged critical result to the on-call backup provider. "
        "Marks the overdue Task as failed, resolves the on-call provider, dispatches "
        "a new Communication, and creates a new acknowledgment Task. "
        "Returns new communication_id and task_id."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "original_task_id": {"type": "string", "description": "The overdue Task ID to mark as failed"},
            "service_request_id": {"type": "string"},
            "patient_id": {"type": "string"},
            "acr_category": {"type": "string", "enum": ["Cat1", "Cat2"]},
            "finding_summary": {"type": "string"},
            "timeout_minutes": {"type": "integer", "description": "Ack timeout for the escalated Task"},
        },
        "required": [
            "original_task_id", "service_request_id", "patient_id",
            "acr_category", "finding_summary", "timeout_minutes",
        ],
    },
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    log.info("tool.escalate", original_task_id=arguments["original_task_id"])

    # Import here to avoid circular imports between tools
    from critcom.tools import dispatch_communication, resolve_provider, track_acknowledgment

    async with FHIRClient.from_env() as client:
        # 1. Mark original task as failed
        await client.update_task_status(arguments["original_task_id"], TaskStatus.FAILED)
        log.info("escalate.original_task_failed", task_id=arguments["original_task_id"])

    # 2. Resolve on-call provider
    provider = await resolve_provider.run(
        {"service_request_id": arguments["service_request_id"], "on_call": True}
    )
    if not provider.get("resolved"):
        return {"error": "Could not resolve on-call provider for escalation", "escalated": False}

    on_call_prac_id = provider["practitioner_id"]
    log.info("escalate.on_call_resolved", practitioner_id=on_call_prac_id, name=provider.get("name"))

    # 3. Dispatch new Communication
    comm_result = await dispatch_communication.run(
        {
            "service_request_id": arguments["service_request_id"],
            "patient_id": arguments["patient_id"],
            "recipient_practitioner_id": on_call_prac_id,
            "acr_category": arguments["acr_category"],
            "finding_summary": f"[ESCALATED] {arguments['finding_summary']}",
        }
    )
    new_comm_id = comm_result["communication_id"]

    # 4. Create new ack Task
    task_result = await track_acknowledgment.run(
        {
            "action": "create",
            "communication_id": new_comm_id,
            "practitioner_id": on_call_prac_id,
            "patient_id": arguments["patient_id"],
            "timeout_minutes": arguments["timeout_minutes"],
        }
    )

    return {
        "escalated": True,
        "on_call_provider": provider.get("name"),
        "on_call_practitioner_id": on_call_prac_id,
        "new_communication_id": new_comm_id,
        "new_task_id": task_result["task_id"],
        "new_deadline": task_result["deadline"],
    }
