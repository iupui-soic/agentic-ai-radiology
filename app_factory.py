"""
create_a2a_app — wrap an ADK Agent into an A2A-compliant ASGI app with
the right middleware, agent card, and security scheme.

Mirrors po-adk-python/shared/app_factory.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any

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
) -> Any:
    """Build the A2A ASGI app. Returns a Starlette app.

    Falls back to a minimal Starlette stub if google-adk's to_a2a is unavailable
    so that the agent code can still be imported and unit-tested without ADK.
    """
    try:
        from google.adk.a2a import to_a2a  # type: ignore
    except ImportError:
        try:
            from google.adk.runtime.a2a import to_a2a  # type: ignore
        except ImportError:
            logger.warning("google-adk a2a not available — using stub app")
            return _stub_app(name, description, url, version, fhir_extension_uri, require_api_key)

    app = to_a2a(
        agent,
        name=name,
        description=description,
        url=url,
        version=version,
    )

    # Attach middleware
    app.add_middleware(ApiKeyMiddleware, require_api_key=require_api_key)
    return app


def _stub_app(name, description, url, version, fhir_extension_uri, require_api_key):
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
            "skills": [],
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
