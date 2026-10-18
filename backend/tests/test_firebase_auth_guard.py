from fastapi import Depends, FastAPI, HTTPException, Request
import pytest

from app.core.config import Settings
from app.core import firebase_auth as auth_guard
from app.core.tenant import current_tenant_id, tenant_namespace


def _request(method: str = "GET", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": "/api/v1/youtube/analysis-jobs/test",
        "headers": headers or [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    })


def _settings(**overrides) -> Settings:
    values = {
        "firebase_auth_required": True,
        "firebase_project_id": "demo-project",
        "firebase_session_cookie_name": "reviveai_session",
        "firebase_csrf_cookie_name": "reviveai_csrf",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_protected_request_requires_session_cookie():
    with pytest.raises(HTTPException) as exc:
        auth_guard.require_authenticated_user(_request(), _settings())
    assert exc.value.status_code == 401


def test_mutating_request_requires_matching_csrf(monkeypatch):
    monkeypatch.setattr(auth_guard, "verify_session_cookie", lambda cookie, settings: {"uid": "u1", "sub": "u1"})
    request = _request(
        "POST",
        [
            (b"cookie", b"reviveai_session=session; reviveai_csrf=expected"),
            (b"x-csrf-token", b"wrong"),
        ],
    )
    with pytest.raises(HTTPException) as exc:
        auth_guard.require_authenticated_user(request, _settings())
    assert exc.value.status_code == 403


def test_matching_session_and_csrf_exposes_user(monkeypatch):
    claims = {"uid": "u1", "sub": "u1", "email": "creator@example.com", "name": "Creator"}
    monkeypatch.setattr(auth_guard, "verify_session_cookie", lambda cookie, settings: claims)
    request = _request(
        "POST",
        [
            (b"cookie", b"reviveai_session=session; reviveai_csrf=expected"),
            (b"x-csrf-token", b"expected"),
        ],
    )
    assert auth_guard.require_authenticated_user(request, _settings()) == claims
    assert request.state.user["uid"] == "u1"
    assert request.state.tenant_id == "user:u1"


def test_custom_tenant_claim_becomes_shared_server_tenant(monkeypatch):
    claims = {"uid": "u1", "sub": "u1", "tenant_id": "team-alpha"}
    monkeypatch.setattr(auth_guard, "verify_session_cookie", lambda cookie, settings: claims)
    request = _request("GET", [(b"cookie", b"reviveai_session=session")])
    auth_guard.require_authenticated_user(request, _settings())
    assert request.state.tenant_id == "tenant:team-alpha"


def test_async_tenant_dependency_propagates_context_to_route(monkeypatch):
    from fastapi.testclient import TestClient

    claims = {"uid": "creator-123", "sub": "creator-123", "email": "creator@example.com"}
    monkeypatch.setattr(auth_guard, "verify_session_cookie", lambda cookie, settings: claims)

    app = FastAPI()

    @app.get("/tenant", dependencies=[Depends(auth_guard.require_tenant_context)])
    async def tenant_probe():
        return {"tenant": current_tenant_id(), "namespace": tenant_namespace()}

    app.dependency_overrides[auth_guard.get_settings] = lambda: _settings()
    client = TestClient(app)
    response = client.get("/tenant", cookies={"reviveai_session": "session"})

    assert response.status_code == 200
    assert response.json()["tenant"] == "user:creator-123"
    assert response.json()["namespace"] == tenant_namespace("user:creator-123")


def test_async_tenant_dependency_honors_trusted_team_claim(monkeypatch):
    from fastapi.testclient import TestClient

    claims = {"uid": "creator-123", "sub": "creator-123", "tenant_id": "team-alpha"}
    monkeypatch.setattr(auth_guard, "verify_session_cookie", lambda cookie, settings: claims)

    app = FastAPI()

    @app.get("/tenant", dependencies=[Depends(auth_guard.require_tenant_context)])
    async def tenant_probe():
        return {"tenant": current_tenant_id()}

    app.dependency_overrides[auth_guard.get_settings] = lambda: _settings()
    client = TestClient(app)
    response = client.get("/tenant", cookies={"reviveai_session": "session"})

    assert response.status_code == 200
    assert response.json()["tenant"] == "tenant:team-alpha"
