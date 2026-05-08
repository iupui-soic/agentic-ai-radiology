"""
create_a2a_app — wrap an ADK Agent into an A2A-compliant ASGI app with
the right middleware, agent card, and security scheme.

Mirrors po-adk-python/shared/app_factory.py.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from shared.middleware import ApiKeyMiddleware

logger = logging.getLogger(__name__)


def create_a2a_app(
    agent: Any,
    name: str,
    description: str,
    url: str,
    version: str = "0.1.0",
    fhir_extension_uri: str | None = None,
    require_api_key: bool = True,
    skills: list[dict[str, Any]] | None = None,
) -> Any:
    """Build the A2A ASGI app. Returns a Starlette app.

    Falls back to a minimal Starlette stub if google-adk's to_a2a is unavailable
    so that the agent code can still be imported and unit-tested without ADK.
    """
    try:
        from a2a.types import AgentCapabilities, AgentCard, AgentSkill
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
    except ImportError as e:
        logger.warning("google-adk a2a not available (%s) — using stub app", e)
        return _stub_app(name, description, url, version, fhir_extension_uri, require_api_key, skills)

    parsed = urlparse(url)
    host = parsed.hostname or "0.0.0.0"
    port = parsed.port or (443 if parsed.scheme == "https" else 8001)

    skill_objects = [AgentSkill(**s) for s in (skills or [])]
    card_data: dict[str, Any] = {
        "name": name,
        "description": description,
        "url": url,
        "version": version,
        "capabilities": AgentCapabilities(streaming=True),
        "default_input_modes": ["text/plain"],
        "default_output_modes": ["text/plain"],
        "skills": skill_objects,
    }
    if require_api_key:
        card_data["security_schemes"] = {
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        }
        card_data["security"] = [{"ApiKeyAuth": []}]
    agent_card = AgentCard(**card_data)

    app = to_a2a(agent, host=host, port=port, agent_card=agent_card)
    app.add_middleware(ApiKeyMiddleware, require_api_key=require_api_key)
    return app


def _stub_app(name, description, url, version, fhir_extension_uri, require_api_key, skills=None):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def agent_card(request):
        card = {
            "name": name,
            "description": description,
            "url": url,
            "version": version,
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": skills or [],
        }
        if require_api_key:
            card["securitySchemes"] = {
                "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            }
            card["security"] = [{"ApiKeyAuth": []}]
        if fhir_extension_uri:
            card["extensions"] = [{"uri": fhir_extension_uri, "required": False}]
        return JSONResponse(card)

    async def post_handler(request):
        return JSONResponse({"error": "ADK runtime not installed; agent endpoint unavailable in stub"}, status_code=501)

    routes = [
        Route("/.well-known/agent-card.json", agent_card, methods=["GET"]),
        Route("/", post_handler, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(ApiKeyMiddleware, require_api_key=require_api_key)
    return app
