"""
ApiKeyMiddleware — validates X-API-Key on every POST and bridges A2A message
metadata into params.metadata so the FHIR hook can read it.

Mirrors the pattern from po-adk-python/shared/middleware.py.
"""

from __future__ import annotations

import json
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Override in production via env vars or a secrets manager
VALID_API_KEYS: set[str] = {
    k for k in [
        os.getenv("CRITCOM_API_KEY", "dev-key-please-change"),
        os.getenv("CRITCOM_API_KEY_SECONDARY"),
    ]
    if k
}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, require_api_key: bool = True) -> None:
        super().__init__(app)
        self.require_api_key = require_api_key

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Always allow agent-card.json
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return await call_next(request)

        if request.method != "POST":
            return await call_next(request)

        if self.require_api_key:
            provided = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
            if not provided:
                logger.warning("security_rejected_missing_api_key path=%s", request.url.path)
                return JSONResponse({"error": "X-API-Key header required"}, status_code=401)
            if provided not in VALID_API_KEYS:
                logger.warning("security_rejected_invalid_api_key path=%s", request.url.path)
                return JSONResponse({"error": "Invalid API key"}, status_code=403)

        # Bridge metadata: copy params.message.metadata → params.metadata so the
        # ADK before_model_callback can find it via session/invocation context.
        try:
            body_bytes = await request.body()
            if body_bytes:
                body = json.loads(body_bytes)
                params = body.get("params") or {}
                msg = params.get("message") or {}
                meta = msg.get("metadata")
                if meta and "metadata" not in params:
                    params["metadata"] = meta
                    body["params"] = params
                    new_bytes = json.dumps(body).encode()
                    # Replace the body in the receive callable
                    async def receive():
                        return {"type": "http.request", "body": new_bytes, "more_body": False}
                    request._receive = receive  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug("middleware_metadata_bridge_skipped error=%s", e)

        return await call_next(request)
