"""
MCP Tool: track_acknowledgment

Creates or checks the FHIR Task that tracks provider acknowledgment of a
critical-result Communication.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from critcom.fhir.client import FHIRClient
from critcom.fhir.models import (
    CodeableConcept,
    Coding,
    Period,
    Reference,
    Task,
    TaskRestriction,
    TaskStatus,
)

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "track_acknowledgment",
    "description": (
        "Create a FHIR Task to track provider acknowledgment of a dispatched Communication, "
        "or check the current status of an existing Task. "
        "Pass communication_id + timeout_minutes to create; pass task_id to check status."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "check", "mark_acknowledged"],
                "description": "create: make a new Task; check: return current status; mark_acknowledged: complete the Task.",
            },
            "communication_id": {"type": "string", "description": "Required for action=create"},
            "practitioner_id": {"type": "string", "description": "Provider expected to acknowledge (required for create)"},
            "patient_id": {"type": "string", "description": "Patient context (required for create)"},
            "timeout_minutes": {"type": "integer", "description": "Ack deadline in minutes (required for create)"},
            "task_id": {"type": "string", "description": "Required for action=check or mark_acknowledged"},
        },
        "required": ["action"],
    },
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    action: str = arguments["action"]
    log.info("tool.track_acknowledgment", action=action)

    async with FHIRClient.from_env() as client:
        if action == "create":
            now = datetime.now(tz=timezone.utc)
            deadline = now + timedelta(minutes=int(arguments["timeout_minutes"]))

            task = Task(
                status=TaskStatus.REQUESTED,
                intent="order",
                priority="stat",
                code=CodeableConcept(
                    coding=[Coding(system="http://critcom/task-type", code="critical-result-ack")],
                    text="Critical result acknowledgment",
                ),
                focus=Reference(reference=f"Communication/{arguments['communication_id']}"),
                **{"for": Reference(reference=f"Patient/{arguments['patient_id']}")},
                authoredOn=now,
                lastModified=now,
                owner=Reference(reference=f"Practitioner/{arguments['practitioner_id']}"),
                restriction=TaskRestriction(
                    repetitions=1,
                    period=Period(start=now, end=deadline),
                ),
            )
            created = await client.create_task(task)
            return {
                "task_id": created.id,
                "status": created.status.value,
                "deadline": deadline.isoformat(),
            }

        elif action == "check":
            task = await client.get_task(arguments["task_id"])
            deadline = task.restriction.period.end if (task.restriction and task.restriction.period) else None
            now = datetime.now(tz=timezone.utc)
            overdue = deadline is not None and now > deadline and task.status not in (
                TaskStatus.COMPLETED, TaskStatus.ACCEPTED
            )
            return {
                "task_id": task.id,
                "status": task.status.value,
                "deadline": deadline.isoformat() if deadline else None,
                "overdue": overdue,
            }

        elif action == "mark_acknowledged":
            updated = await client.update_task_status(arguments["task_id"], TaskStatus.COMPLETED)
            return {"task_id": updated.id, "status": updated.status.value}

        return {"error": f"Unknown action: {action}"}
