from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models import AuthSession, User
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.auth import build_me_payload, create_dev_session, upsert_dev_user
from backend.app.services.knowledge_access import KnowledgeAccessPolicy

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)


@router.post("/login/dev")
def login_dev(body: DevLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings.DEV_AUTH_ENABLED:
        return Response(status_code=404)
    username = body.username.strip()
    user = upsert_dev_user(db, username=username, display_name=body.display_name.strip() if body.display_name else None)
    session = create_dev_session(db, user=user, request=request)
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session.id,
        httponly=True,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
    )
    return build_me_payload(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        status=user.status,
        tenant_id=user.username,
        auth_mode="session",
        team_role="member",
    )


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        db.query(AuthSession).filter_by(id=session_id).delete()
        db.commit()
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"detail": "logged_out"}


@router.get("/me")
def me(actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    # No session and no real header identity -> genuinely unauthenticated.
    if actor.auth_mode == "header-fallback" and actor.actor_id == "default-user" and not actor.user_pk:
        raise ApiProblem(401, "AUTH_NOT_AUTHENTICATED", "Not authenticated")

    team_role = KnowledgeAccessPolicy(db).get_team_role(actor)

    if actor.auth_mode == "session" and actor.user_pk:
        user = db.query(User).filter_by(id=actor.user_pk).one_or_none()
        if user is None:
            raise ApiProblem(401, "AUTH_SESSION_INVALID", "Session user not found")
        return build_me_payload(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            status=user.status,
            tenant_id=actor.tenant_id,
            auth_mode="session",
            team_role=team_role,
        )

    return build_me_payload(
        username=actor.actor_id,
        display_name=actor.actor_id,
        status="active",
        tenant_id=actor.tenant_id,
        auth_mode=actor.auth_mode,
        team_role=team_role,
    )
