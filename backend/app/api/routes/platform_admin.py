"""Read-only platform administration; intentionally outside creator tenant APIs."""
from __future__ import annotations

from typing import Any
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.config import Settings, get_settings
from app.core.firebase_auth import require_authenticated_user, firebase_admin_auth

router = APIRouter(prefix="/api/v1/admin", tags=["platform-admin"])


def require_platform_admin(
    claims: dict[str, Any] = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    # Never allow the local-development identity to access cross-tenant data.
    if not settings.firebase_auth_required:
        raise HTTPException(status_code=403, detail="Platform administration requires Firebase authentication.")
    if claims.get("platform_role") != "PLATFORM_ADMIN":
        raise HTTPException(status_code=403, detail="Platform administrator permission required.")
    return claims


@router.get("/me")
def admin_me(claims: dict[str, Any] = Depends(require_platform_admin)):
    return {"uid": claims["uid"], "platform_role": "PLATFORM_ADMIN"}


@router.get("/users")
def list_platform_users(
    limit: int = Query(default=25, ge=1, le=100),
    page_token: str | None = Query(default=None, max_length=4096),
    _: dict[str, Any] = Depends(require_platform_admin),
    settings: Settings = Depends(get_settings),
):
    auth, app = firebase_admin_auth(settings)
    try:
        result = auth.list_users(page_token=page_token or None, max_results=limit, app=app)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid user-directory page token.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Firebase user directory is temporarily unavailable.") from exc
    users = []
    for user in result.users:
        metadata = user.user_metadata
        users.append({
            "uid": user.uid,
            "email": user.email,
            "display_name": user.display_name,
            "photo_url": user.photo_url,
            "disabled": user.disabled,
            "email_verified": user.email_verified,
            "created_at": metadata.creation_timestamp if metadata else None,
            "last_sign_in_at": metadata.last_sign_in_timestamp if metadata else None,
            "platform_role": (user.custom_claims or {}).get("platform_role") if user.custom_claims else None,
        })
    return {"users": users, "next_page_token": result.next_page_token}

@router.get("/costs/summary")
def platform_cost_summary(
    limit: int = Query(default=500, ge=1, le=2000),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    _: dict[str, Any] = Depends(require_platform_admin),
):
    """Bounded ledger-only reporting; never guesses channel ownership."""
    from app.services.platform_cost_reporting_service import get_platform_cost_snapshot
    try:
        return get_platform_cost_snapshot(limit=limit, from_date=from_date, to_date=to_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Platform ledger summary failed")
        raise HTTPException(status_code=503, detail="Production-cost reporting is temporarily unavailable.") from exc
