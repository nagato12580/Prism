# prism/backend/app/api/model_providers.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import ModelProvider
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessPolicy
from backend.app.services.model_cache import decrypt_secret, mask_secret
from backend.app.services import model_providers as svc

router = APIRouter(prefix="/model-providers", tags=["model-providers"])


class ProviderCreate(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    provider_type: str = "openai"
    base_url: str = Field(min_length=1)
    api_key_env: str | None = None
    api_key: str | None = None
    capabilities: dict | None = None
    enabled_models: list[str] = []
    headers_json: dict | None = None
    extra_json: dict | None = None
    is_enabled: bool = True


class ProviderUpdate(BaseModel):
    display_name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    capabilities: dict | None = None
    enabled_models: list[str] | None = None
    headers_json: dict | None = None
    extra_json: dict | None = None
    is_enabled: bool | None = None


class DefaultModelBody(BaseModel):
    spec: str = Field(min_length=1)


def _require_admin(policy: KnowledgeAccessPolicy, actor: ActorContext) -> None:
    if not policy.is_team_admin(actor):
        raise ApiProblem(403, "ADMIN_ACCESS_REQUIRED", "Admin access required")


def _dto(p: ModelProvider) -> dict:
    plain = decrypt_secret(p.api_key)
    return {
        "provider_id": p.provider_id,
        "display_name": p.display_name,
        "provider_type": p.provider_type,
        "base_url": p.base_url,
        "api_key_env": p.api_key_env,
        "has_api_key": bool(plain) or bool(p.api_key_env),
        "api_key_masked": mask_secret(plain),
        "capabilities": p.capabilities,
        "enabled_models": p.enabled_models or [],
        "is_enabled": p.is_enabled,
        "is_builtin": p.is_builtin,
    }


@router.get("/providers")
def list_providers(actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    return {"items": [_dto(p) for p in svc.list_providers(db)]}


@router.post("/providers")
def create_provider(body: ProviderCreate, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        row = svc.create_provider(db, **body.model_dump())
    except svc.ProviderConflict as e:
        raise ApiProblem(409, "PROVIDER_CONFLICT", str(e))
    except svc.ProviderValidationError as e:
        raise ApiProblem(422, "INVALID_PROVIDER", str(e))
    return _dto(row)


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, body: ProviderUpdate, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        row = svc.update_provider(db, provider_id=provider_id, **body.model_dump(exclude_unset=True))
    except svc.ProviderNotFound as e:
        raise ApiProblem(404, "PROVIDER_NOT_FOUND", str(e))
    except svc.ProviderInUse as e:
        raise ApiProblem(409, "PROVIDER_IN_USE", str(e))
    return _dto(row)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        svc.delete_provider(db, provider_id=provider_id)
    except svc.ProviderNotFound as e:
        raise ApiProblem(404, "PROVIDER_NOT_FOUND", str(e))
    except svc.ProviderInUse as e:
        raise ApiProblem(409, "PROVIDER_IN_USE", str(e))
    return {"detail": "deleted"}


@router.get("/models")
def list_models(actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    models = []
    for p in svc.list_providers(db):
        if not p.is_enabled:
            continue
        for model_id in (p.enabled_models or []):
            models.append({"spec": f"{p.provider_id}:{model_id}", "provider_id": p.provider_id, "model_id": model_id})
    return {"items": models}


@router.get("/models/status")
def model_status(spec: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    return svc.test_connection(spec)


@router.get("/config/default")
def get_default(actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    return {"spec": svc.get_default_chat_model(db)}


@router.put("/config/default")
def set_default(body: DefaultModelBody, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        svc.set_default_chat_model(db, body.spec)
    except svc.ProviderValidationError as e:
        raise ApiProblem(422, "INVALID_DEFAULT_MODEL", str(e))
    return {"spec": body.spec}


@router.post("/cache/refresh")
def refresh_cache(actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    from backend.app.services.model_cache import refresh_model_cache

    refresh_model_cache(db)
    return {"detail": "refreshed"}
