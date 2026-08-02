# backend/app/security/actor.py
from typing import Annotated

from fastapi import Header
from pydantic import BaseModel, ConfigDict


class ActorContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    request_id: str = ""


def get_actor_context(
    x_prism_actor: Annotated[str | None, Header()] = None,
    x_prism_tenant: Annotated[str | None, Header()] = None,
    x_prism_roles: Annotated[str | None, Header()] = None,
) -> ActorContext:
    actor_id = x_prism_actor or "default-user"
    roles = tuple(
        role.strip()
        for role in (x_prism_roles or "").split(",")
        if role.strip()
    )
    return ActorContext(actor_id=actor_id, tenant_id=x_prism_tenant or actor_id, roles=roles)
