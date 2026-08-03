from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import AuthSession, User
from backend.app.utils.time import local_now


@dataclass(frozen=True)
class AuthIdentity:
    user: User
    session: AuthSession


def build_me_payload(*, username: str, display_name: str, status: str, tenant_id: str, auth_mode: str, team_role: str | None, user_id: str | None = None) -> dict:
    return {
        "id": user_id or username,
        "username": username,
        "display_name": display_name,
        "email": None,
        "status": status,
        "tenant_id": tenant_id,
        "auth_mode": auth_mode,
        "team_role": team_role,
    }


def upsert_dev_user(db: Session, *, username: str, display_name: str | None) -> User:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username, display_name=display_name or username, status="active")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        db.commit()
        db.refresh(user)
    return user


def create_dev_session(db: Session, *, user: User, request: Request) -> AuthSession:
    row = AuthSession(
        user_id=user.id,
        expires_at=local_now() + timedelta(hours=settings.SESSION_TTL_HOURS),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
