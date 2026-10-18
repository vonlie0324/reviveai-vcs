from __future__ import annotations

import hmac
from functools import lru_cache
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.tenant import reset_current_tenant, set_current_tenant


_FIREBASE_APP_NAME = "reviveai"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@lru_cache(maxsize=4)
def _firebase_app(project_id: str):
    if not project_id:
        raise RuntimeError("FIREBASE_PROJECT_ID is not configured.")
    try:
        import firebase_admin
    except ImportError as exc:
        raise RuntimeError("firebase-admin is not installed. Run pip install -r requirements.txt.") from exc
    try:
        return firebase_admin.get_app(_FIREBASE_APP_NAME)
    except ValueError:
        return firebase_admin.initialize_app(
            options={"projectId": project_id},
            name=_FIREBASE_APP_NAME,
        )


def _dev_user() -> Dict[str, Any]:
    return {
        "uid": "local-dev-user",
        "sub": "local-dev-user",
        "email": "local@reviveai.dev",
        "email_verified": True,
        "name": "Local Developer",
        "picture": None,
        "firebase": {"sign_in_provider": "development"},
    }


def verify_session_cookie(session_cookie: str, settings: Settings) -> Dict[str, Any]:
    if not settings.firebase_auth_required:
        return _dev_user()
    if not settings.effective_firebase_project_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Authentication is not configured on the backend.",
        )
    try:
        from firebase_admin import auth as firebase_auth
        app = _firebase_app(settings.effective_firebase_project_id)
        return firebase_auth.verify_session_cookie(
            session_cookie,
            check_revoked=settings.firebase_check_revoked,
            app=app,
        )
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your ReviveAI session is missing, expired, or no longer valid. Please sign in again.",
        ) from exc




def tenant_id_from_claims(claims: Dict[str, Any]) -> str:
    """Resolve the server-side security boundary for this authenticated session.

    By default every Firebase uid is its own tenant. A future Business/Team setup can
    assign a trusted Firebase custom claim named ``tenant_id`` to intentionally share
    backend resources inside one organization. Client-provided tenant identifiers are
    never accepted.
    """
    uid = str(claims.get("uid") or claims.get("sub") or "").strip()
    if not uid:
        # Never collapse malformed authenticated sessions into a shared ``user:``
        # namespace. Authentication may have succeeded upstream, but tenant identity
        # is mandatory before any creator-scoped store can be touched.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated session is missing its Firebase user identity. Please sign in again.",
        )

    tenant_claim = claims.get("tenant_id")
    if isinstance(tenant_claim, str) and tenant_claim.strip():
        return f"tenant:{tenant_claim.strip()}"
    return f"user:{uid}"


def require_authenticated_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    if not settings.firebase_auth_required:
        claims = _dev_user()
        tenant_id = tenant_id_from_claims(claims)
        request.state.tenant_id = tenant_id
        request.state.user = claims
        return claims

    session_cookie = request.cookies.get(settings.firebase_session_cookie_name)
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
        )

    claims = verify_session_cookie(session_cookie, settings)

    if request.method.upper() not in _SAFE_METHODS:
        csrf_cookie = request.cookies.get(settings.firebase_csrf_cookie_name, "")
        csrf_header = request.headers.get("X-CSRF-Token", "")
        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Security token validation failed. Refresh the page and try again.",
            )

    tenant_id = tenant_id_from_claims(claims)
    request.state.tenant_id = tenant_id
    request.state.user = claims
    return claims


async def require_tenant_context(
    request: Request,
    claims: Dict[str, Any] = Depends(require_authenticated_user),
):
    """Bind the verified tenant to the async request context.

    FastAPI executes normal ``def`` dependencies in a worker thread. ContextVar
    mutations made inside that worker do not propagate back into the async route
    task. Tenant-scoped stores therefore must be bound from an async dependency
    that runs in the same context as the endpoint itself.

    The sync authentication dependency still owns session/CSRF verification and
    records the trusted tenant on ``request.state``. This wrapper establishes the
    ContextVar for the full endpoint lifetime and reliably resets it afterwards.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        tenant_id = tenant_id_from_claims(claims)
        request.state.tenant_id = tenant_id
    token = set_current_tenant(tenant_id)
    try:
        yield claims
    finally:
        reset_current_tenant(token)


def claims_to_user(claims: Dict[str, Any]) -> Dict[str, Any]:
    firebase_claims = claims.get("firebase") if isinstance(claims.get("firebase"), dict) else {}
    email = claims.get("email")
    name = claims.get("name") or (email.split("@", 1)[0] if isinstance(email, str) and email else "ReviveAI creator")
    return {
        "uid": claims.get("uid") or claims.get("sub") or "",
        "email": email,
        "name": name,
        "picture": claims.get("picture"),
        "email_verified": bool(claims.get("email_verified")),
        "provider": firebase_claims.get("sign_in_provider"),
    }


def firebase_admin_auth(settings: Settings):
    if not settings.effective_firebase_project_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Authentication is not configured on the backend.",
        )
    try:
        from firebase_admin import auth as firebase_auth
        return firebase_auth, _firebase_app(settings.effective_firebase_project_id)
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
