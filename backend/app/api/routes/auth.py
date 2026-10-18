from __future__ import annotations

import secrets
import time
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.firebase_auth import claims_to_user, firebase_admin_auth, require_tenant_context
from app.services.legacy_adoption_service import LegacyWorkspaceAdoptionService


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class SessionRequest(BaseModel):
    id_token: str = Field(min_length=20)


class AuthUser(BaseModel):
    uid: str
    email: Optional[str] = None
    name: str
    picture: Optional[str] = None
    email_verified: bool = False
    provider: Optional[str] = None


class LegacyAdoptionStatus(BaseModel):
    eligible: bool
    legacy_items: int = 0
    legacy_productions: int = 0
    production_titles: list[str] = Field(default_factory=list)
    already_adopted: bool = False
    message: str


class LegacyAdoptionResultResponse(BaseModel):
    copied: int
    skipped: int
    legacy_productions: int
    production_titles: list[str] = Field(default_factory=list)
    message: str


def _legacy_adoption_allowed(claims, settings: Settings) -> bool:
    uid = str(claims.get("uid") or claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    allowed_uids = {item.strip() for item in settings.legacy_adoption_allowed_uids if item.strip()}
    allowed_emails = {item.strip().lower() for item in settings.legacy_adoption_allowed_emails if item.strip()}
    if uid and uid in allowed_uids:
        return True
    return bool(email and claims.get("email_verified") and email in allowed_emails)


def _validate_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is not allowed.")


def _set_auth_cookies(response: Response, session_cookie: str, csrf_token: str, settings: Settings) -> None:
    max_age = settings.firebase_session_days * 24 * 60 * 60
    cookie_common = {
        "max_age": max_age,
        "secure": settings.firebase_cookie_secure,
        "samesite": settings.firebase_cookie_samesite,
        "path": "/",
    }
    response.set_cookie(
        key=settings.firebase_session_cookie_name,
        value=session_cookie,
        httponly=True,
        **cookie_common,
    )
    response.set_cookie(
        key=settings.firebase_csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        **cookie_common,
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.firebase_session_cookie_name,
        path="/",
        secure=settings.firebase_cookie_secure,
        samesite=settings.firebase_cookie_samesite,
    )
    response.delete_cookie(
        settings.firebase_csrf_cookie_name,
        path="/",
        secure=settings.firebase_cookie_secure,
        samesite=settings.firebase_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/session", response_model=AuthUser)
def create_session(
    payload: SessionRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    if not settings.firebase_auth_required:
        raise HTTPException(status_code=409, detail="Firebase authentication is disabled in this environment.")

    _validate_origin(request, settings)
    admin_auth, app = firebase_admin_auth(settings)
    try:
        decoded = admin_auth.verify_id_token(payload.id_token, app=app)
        auth_time = float(decoded.get("auth_time") or 0)
        if not auth_time or time.time() - auth_time > settings.firebase_recent_sign_in_seconds:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please sign in again before creating a ReviveAI session.",
            )
        expires_in = timedelta(days=settings.firebase_session_days)
        session_cookie = admin_auth.create_session_cookie(payload.id_token, expires_in=expires_in, app=app)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase could not create a secure ReviveAI session.",
        ) from exc

    csrf_token = secrets.token_urlsafe(32)
    _set_auth_cookies(response, session_cookie, csrf_token, settings)
    return claims_to_user(decoded)


@router.get("/me", response_model=AuthUser)
def get_me(claims=Depends(require_tenant_context)):
    return claims_to_user(claims)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
):
    _validate_origin(request, settings)
    _clear_auth_cookies(response, settings)
    return response


@router.get("/legacy-adoption/status", response_model=LegacyAdoptionStatus)
def legacy_adoption_status(
    request: Request,
    claims=Depends(require_tenant_context),
    settings: Settings = Depends(get_settings),
):
    if not _legacy_adoption_allowed(claims, settings):
        return LegacyAdoptionStatus(
            eligible=False,
            message=(
                "Legacy workspace recovery is not authorized for this account. "
                "A server administrator must explicitly allow this Firebase UID or verified email before pre-isolation data can be adopted."
            ),
        )

    logical_tenant = getattr(request.state, "tenant_id", None)
    if not logical_tenant:
        raise HTTPException(status_code=500, detail="Authenticated tenant context is unavailable.")
    inventory = LegacyWorkspaceAdoptionService(settings).inventory(logical_tenant)
    return LegacyAdoptionStatus(
        eligible=True,
        legacy_items=inventory.item_count,
        legacy_productions=inventory.production_count,
        production_titles=list(inventory.production_titles),
        already_adopted=inventory.already_adopted,
        message=(
            "Legacy ReviveAI data is available for one-time recovery into your private workspace."
            if inventory.item_count
            else "No pre-isolation legacy workspace data was found on this server."
        ),
    )


@router.post("/legacy-adoption/adopt", response_model=LegacyAdoptionResultResponse)
def adopt_legacy_workspace(
    request: Request,
    claims=Depends(require_tenant_context),
    settings: Settings = Depends(get_settings),
):
    if not _legacy_adoption_allowed(claims, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Legacy workspace recovery is not authorized for this account.",
        )
    logical_tenant = getattr(request.state, "tenant_id", None)
    if not logical_tenant:
        raise HTTPException(status_code=500, detail="Authenticated tenant context is unavailable.")

    service = LegacyWorkspaceAdoptionService(settings)
    inventory = service.inventory(logical_tenant)
    if inventory.item_count == 0:
        return LegacyAdoptionResultResponse(
            copied=0,
            skipped=0,
            legacy_productions=0,
            production_titles=[],
            message="No pre-isolation legacy workspace data was found to recover.",
        )

    result = service.adopt(logical_tenant)
    return LegacyAdoptionResultResponse(
        copied=result.copied,
        skipped=result.skipped,
        legacy_productions=result.production_count,
        production_titles=list(result.production_titles),
        message=(
            "Legacy workspace recovered into your authenticated tenant. "
            "The original unscoped files were kept as rollback copies."
        ),
    )
