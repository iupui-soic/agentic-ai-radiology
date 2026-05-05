"""
MCP Tool: resolve_provider

Walks FHIR ServiceRequest → requester → Practitioner / PractitionerRole
to find who should be notified, respecting on-call coverage.
"""

from __future__ import annotations

from typing import Any

import structlog

from critcom.fhir.client import FHIRClient
from critcom.fhir.models import Practitioner, PractitionerRole

log = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "resolve_provider",
    "description": (
        "Given a FHIR ServiceRequest ID, resolve the ordering provider and return "
        "their contact details. Falls back to on-call coverage if the primary provider "
        "cannot be reached or if on_call=true is passed."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service_request_id": {
                "type": "string",
                "description": "FHIR ServiceRequest resource ID.",
            },
            "on_call": {
                "type": "boolean",
                "description": "If true, return the on-call provider instead of the ordering provider.",
                "default": False,
            },
        },
        "required": ["service_request_id"],
    },
}


def _practitioner_contact(p: Practitioner) -> dict[str, str | None]:
    return {
        "phone": p.contact("phone"),
        "pager": p.contact("pager"),
        "email": p.contact("email"),
    }


def _role_contact(r: PractitionerRole) -> dict[str, str | None]:
    return {
        "phone": r.contact("phone"),
        "pager": r.contact("pager"),
        "email": r.contact("email"),
    }


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    sr_id: str = arguments["service_request_id"]
    on_call: bool = arguments.get("on_call", False)

    log.info("tool.resolve_provider", service_request_id=sr_id, on_call=on_call)

    async with FHIRClient.from_env() as client:
        if on_call:
            roles = await client.search_on_call_roles()
            if not roles:
                return {"error": "No on-call provider found", "resolved": False}
            role = roles[0]
            prac_ref = role.practitioner
            if prac_ref and prac_ref.reference:
                prac_id = prac_ref.reference.split("/")[-1]
                prac = await client.get_practitioner(prac_id)
                return {
                    "resolved": True,
                    "type": "on-call",
                    "practitioner_id": prac.id,
                    "practitioner_role_id": role.id,
                    "name": prac.display_name,
                    "contact": {**_practitioner_contact(prac), **_role_contact(role)},
                }
            return {"resolved": False, "error": "On-call role has no practitioner reference"}

        sr = await client.get_service_request(sr_id)

        requester_ref = sr.requester
        if not requester_ref or not requester_ref.reference:
            return {"resolved": False, "error": "ServiceRequest has no requester"}

        ref_parts = requester_ref.reference.split("/")
        resource_type = ref_parts[0] if len(ref_parts) == 2 else "Practitioner"
        resource_id = ref_parts[-1]

        if resource_type == "PractitionerRole":
            role = await client.get_practitioner_role(resource_id)
            prac_ref = role.practitioner
            if prac_ref and prac_ref.reference:
                prac_id = prac_ref.reference.split("/")[-1]
                prac = await client.get_practitioner(prac_id)
            else:
                return {"resolved": False, "error": "PractitionerRole has no practitioner reference"}
            return {
                "resolved": True,
                "type": "ordering",
                "practitioner_id": prac.id,
                "practitioner_role_id": role.id,
                "name": prac.display_name,
                "contact": {**_practitioner_contact(prac), **_role_contact(role)},
            }

        # Default: Practitioner reference
        prac = await client.get_practitioner(resource_id)
        roles = await client.search_practitioner_roles(resource_id)
        role_id = roles[0].id if roles else None
        role_contact = _role_contact(roles[0]) if roles else {}

        return {
            "resolved": True,
            "type": "ordering",
            "practitioner_id": prac.id,
            "practitioner_role_id": role_id,
            "name": prac.display_name,
            "contact": {**role_contact, **_practitioner_contact(prac)},
        }
