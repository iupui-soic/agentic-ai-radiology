"""Tests for ApiKeyMiddleware — auth enforcement and key loading.

Covers the hardening: no baked-in default key, fail-closed (503) when auth is
required but no key is configured, constant-time comparison, and the
agent-card bypass.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from shared import middleware as mw
from shared.middleware import ApiKeyMiddleware


async def _ok(request):
    return JSONResponse({"ok": True})


def _make_client(require_api_key: bool) -> TestClient:
    app = Starlette(
        routes=[
            Route("/", _ok, methods=["GET", "POST"]),
            Route("/.well-known/agent-card.json", _ok, methods=["GET"]),
        ]
    )
    app.add_middleware(ApiKeyMiddleware, require_api_key=require_api_key)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Key loading + constant-time check
# ---------------------------------------------------------------------------

class TestKeyLoading:
    def test_no_env_means_no_keys(self, monkeypatch):
        monkeypatch.delenv("CRITCOM_API_KEY", raising=False)
        monkeypatch.delenv("CRITCOM_API_KEY_SECONDARY", raising=False)
        assert mw._load_api_keys() == set()

    def test_loads_primary_and_secondary(self, monkeypatch):
        monkeypatch.setenv("CRITCOM_API_KEY", "primary")
        monkeypatch.setenv("CRITCOM_API_KEY_SECONDARY", "secondary")
        assert mw._load_api_keys() == {"primary", "secondary"}

    def test_key_accepted_membership(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", {"good"})
        assert mw._key_accepted("good") is True
        assert mw._key_accepted("bad") is False


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

class TestEnforcement:
    def test_fail_closed_when_required_but_no_key(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", set())
        r = _make_client(require_api_key=True).post("/", json={})
        assert r.status_code == 503

    def test_missing_header_rejected(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", {"secret"})
        r = _make_client(require_api_key=True).post("/", json={})
        assert r.status_code == 401

    def test_wrong_key_rejected(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", {"secret"})
        r = _make_client(require_api_key=True).post("/", headers={"X-API-Key": "nope"}, json={})
        assert r.status_code == 403

    def test_correct_key_accepted(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", {"secret"})
        r = _make_client(require_api_key=True).post("/", headers={"X-API-Key": "secret"}, json={})
        assert r.status_code == 200

    def test_published_default_not_accepted(self, monkeypatch):
        # The old code accepted "dev-key-please-change" by default — it must not.
        monkeypatch.setattr(mw, "VALID_API_KEYS", {"secret"})
        r = _make_client(require_api_key=True).post(
            "/", headers={"X-API-Key": "dev-key-please-change"}, json={}
        )
        assert r.status_code == 403

    def test_disabled_auth_allows_all(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", set())
        r = _make_client(require_api_key=False).post("/", json={})
        assert r.status_code == 200

    def test_agent_card_bypasses_auth(self, monkeypatch):
        monkeypatch.setattr(mw, "VALID_API_KEYS", {"secret"})
        r = _make_client(require_api_key=True).get("/.well-known/agent-card.json")
        assert r.status_code == 200
