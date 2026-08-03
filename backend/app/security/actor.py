# backend/app/security/actor.py
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models import AuthSession, User
from backend.app.utils.time import local_now


class ActorContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    request_id: str = ""
    auth_mode: str = "header-fallback"
    user_pk: str | None = None


def _resolve_session_actor(request: Request, db: Session) -> ActorContext | None:
    """Resolve identity from the HttpOnly session cookie.

    Returns ``None`` only when no session cookie is present (caller falls back
    to header-based auth). A present-but-invalid session is a hard error so a
    stale cookie can never silently downgrade to header identity.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        return None
    row = db.query(AuthSession).filter_by(id=session_id).one_or_none()
    if row is None or row.expires_at < local_now():
        raise HTTPException(status_code=401, detail={"code": "AUTH_SESSION_INVALID", "message": "Invalid or expired session"})
    user = db.query(User).filter_by(id=row.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "AUTH_SESSION_INVALID", "message": "Session user not found"})
    if user.status != "active":
        raise HTTPException(status_code=403, detail={"code": "AUTH_USER_DISABLED", "message": "User is disabled"})
    return ActorContext(
        actor_id=user.username,
        tenant_id=user.username,
        auth_mode="session",
        user_pk=user.id,
        roles=(),
    )


def get_actor_context(
    request: Request,
    db: Session = Depends(get_db),
    x_prism_actor: Annotated[str | None, Header()] = None,
    x_prism_tenant: Annotated[str | None, Header()] = None,
    x_prism_roles: Annotated[str | None, Header()] = None,
) -> ActorContext:
    session_actor = _resolve_session_actor(request, db)
    if session_actor is not None:
        return session_actor

    if settings.HEADER_AUTH_FALLBACK_ENABLED:
        actor_id = x_prism_actor or "default-user"
        roles = tuple(
            role.strip()
            for role in (x_prism_roles or "").split(",")
            if role.strip()
        )
        return ActorContext(
            actor_id=actor_id,
            tenant_id=x_prism_tenant or actor_id,
            roles=roles,
            auth_mode="header-fallback",
        )

    # Header fallback disabled and no session: last-resort compat identity.
    return ActorContext(actor_id="default-user", tenant_id="default-user")
