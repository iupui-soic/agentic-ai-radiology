"""
MCP Tool: query_audit

Returns a human-readable audit trail of all Communications and Tasks
related to a ServiceRequest (critical-result case).
"""

from __future__ import annotations

from typing import Any

import structlog

from critcom.fhir.client import FHIRClient

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "query_audit",
    "description": (
        "Return the full audit trail for a critical-result case: all Communications "
        "dispatched and all acknowledgment Tasks, with their statuses and timestamps. "
        "Provide service_request_id and/or patient_id."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service_request_id": {"type": "string"},
            "patient_id": {"type": "string"},
        },
        "required": [],
    },
}


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    sr_id: str | None = arguments.get("service_request_id")
    patient_id: str | None = arguments.get("patient_id")

    log.info("tool.query_audit", service_request_id=sr_id, patient_id=patient_id)

    async with FHIRClient.from_env() as client:
        audit = await client.search_audit(service_request_id=sr_id, patient_id=patient_id)

    comms = audit.get("communications", [])
    tasks = audit.get("tasks", [])

    # Build a readable summary
    summary_lines: list[str] = []
    for c in comms:
        comm_id = c.get("id", "?")
        status = c.get("status", "?")
        sent = c.get("sent", "?")
        payload = (c.get("payload") or [{}])[0].get("contentString", "")
        summary_lines.append(f"Communication {comm_id}: status={status}, sent={sent}, finding={payload[:80]}")

    for t in tasks:
        task_id = t.get("id", "?")
        status = t.get("status", "?")
        modified = t.get("lastModified", "?")
        summary_lines.append(f"Task {task_id}: status={status}, lastModified={modified}")

    return {
        "total_communications": len(comms),
        "total_tasks": len(tasks),
        "summary": "\n".join(summary_lines) if summary_lines else "No records found.",
        "communications": comms,
        "tasks": tasks,
    }
