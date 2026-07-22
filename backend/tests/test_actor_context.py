# backend/tests/test_actor_context.py
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


def test_actor_dependency_supplies_compatibility_actor():
    from backend.app.security.actor import ActorContext, get_actor_context

    app = FastAPI()

    @app.get("/actor")
    def actor(actor: ActorContext = Depends(get_actor_context)):
        return actor.model_dump()

    body = TestClient(app).get("/actor").json()
    assert body["actor_id"] == "default-user"
    assert body["tenant_id"] == "default-user"


def test_actor_accepts_custom_headers():
    from backend.app.security.actor import ActorContext, get_actor_context

    app = FastAPI()

    @app.get("/actor")
    def actor(actor: ActorContext = Depends(get_actor_context)):
        return actor.model_dump()

    body = TestClient(app).get(
        "/actor",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"},
    ).json()
    assert body["actor_id"] == "alice"
    assert body["tenant_id"] == "tenant-a"


def test_actor_is_immutable():
    from backend.app.security.actor import ActorContext

    actor = ActorContext(actor_id="alice", tenant_id="tenant-a", roles=("reader",))
    try:
        actor.actor_id = "bob"
    except Exception:
        pass
    else:
        raise AssertionError("ActorContext is not frozen")
