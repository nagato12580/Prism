# backend/app/api/team_admin.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import TeamMember
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessPolicy
from backend.app.services.team_members import (
    TeamMemberConflict,
    TeamMemberLastAdminDenied,
    TeamMemberNotFound,
    TeamMemberSelfOperationDenied,
    TeamMemberValidationError,
    add_team_member,
    list_team_members,
    remove_team_member,
    update_team_member,
)

router = APIRouter(prefix="/team/admin", tags=["team-admin"])


class TeamMemberCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    role: str
    status: str = "active"


class TeamMemberUpdate(BaseModel):
    role: str | None = None
    status: str | None = None


class TeamMemberDto(BaseModel):
    user_id: str
    role: str
    status: str
    created_at: object | None = None
    updated_at: object | None = None

    model_config = {"from_attributes": True}


class TeamMemberListResponse(BaseModel):
    items: list[TeamMemberDto]
    total: int


def _require_admin(policy: KnowledgeAccessPolicy, actor: ActorContext) -> None:
    if not policy.is_team_admin(actor):
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Admin access required")


def _team_member_dto(row: TeamMember) -> dict:
    return {
        "user_id": row.user_id,
        "role": row.role,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/members", response_model=TeamMemberListResponse)
def list_members(
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    items = list_team_members(db, tenant_id=actor.tenant_id)
    return TeamMemberListResponse(
        items=[_team_member_dto(m) for m in items],
        total=len(items),
    )


@router.post("/members", response_model=TeamMemberDto)
def create_member(
    body: TeamMemberCreate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        row = add_team_member(
            db,
            actor=actor,
            user_id=body.user_id,
            role=body.role,
            status=body.status,
        )
    except TeamMemberValidationError as e:
        raise ApiProblem(422, "INVALID_MEMBER_FIELD", str(e))
    except TeamMemberConflict as e:
        raise ApiProblem(409, "MEMBER_CONFLICT", str(e))
    return _team_member_dto(row)


@router.put("/members/{user_id}", response_model=TeamMemberDto)
def update_member(
    user_id: str,
    body: TeamMemberUpdate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        row = update_team_member(
            db,
            actor=actor,
            user_id=user_id,
            role=body.role,
            status=body.status,
        )
    except TeamMemberSelfOperationDenied as e:
        raise ApiProblem(409, "SELF_OPERATION_DENIED", str(e))
    except TeamMemberLastAdminDenied as e:
        raise ApiProblem(409, "LAST_ADMIN_OPERATION_DENIED", str(e))
    except TeamMemberNotFound as e:
        raise ApiProblem(404, "MEMBER_NOT_FOUND", str(e))
    except TeamMemberValidationError as e:
        raise ApiProblem(422, "INVALID_MEMBER_FIELD", str(e))
    except TeamMemberConflict as e:
        raise ApiProblem(422, "INVALID_MEMBER_FIELD", str(e))
    return _team_member_dto(row)


@router.delete("/members/{user_id}")
def delete_member(
    user_id: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        remove_team_member(db, actor=actor, user_id=user_id)
    except TeamMemberSelfOperationDenied as e:
        raise ApiProblem(409, "SELF_OPERATION_DENIED", str(e))
    except TeamMemberLastAdminDenied as e:
        raise ApiProblem(409, "LAST_ADMIN_OPERATION_DENIED", str(e))
    except TeamMemberNotFound as e:
        raise ApiProblem(404, "MEMBER_NOT_FOUND", str(e))
    return {"detail": "deleted"}
