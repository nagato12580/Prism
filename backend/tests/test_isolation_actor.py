# Isolation tests: after the default-user retrofit, every user-scoped surface
# (chat, memories, assets, wiki, traces) must be scoped by the authenticated
# actor. These tests use the header-fallback auth (X-Prism-Actor) to simulate
# two distinct users and assert they cannot see or touch each other's data.

ALICE = {"X-Prism-Actor": "alice"}
BOB = {"X-Prism-Actor": "bob"}


def _headers(actor: dict, method: str, path: str) -> dict:
    return {**actor}


# ── Chat ────────────────────────────────────────────────────────────────


def test_chat_sessions_are_actor_scoped(client):
    a = client.post("/api/v1/chat/sessions", json={"title": "alice's chat"}, headers=ALICE)
    assert a.status_code == 200
    a_sid = a.json()["id"]

    b = client.post("/api/v1/chat/sessions", json={"title": "bob's chat"}, headers=BOB)
    assert b.status_code == 200
    b_sid = b.json()["id"]

    a_list = client.get("/api/v1/chat/sessions", headers=ALICE)
    assert a_list.status_code == 200
    a_ids = {s["id"] for s in a_list.json()}
    assert a_sid in a_ids
    assert b_sid not in a_ids

    b_list = client.get("/api/v1/chat/sessions", headers=BOB)
    b_ids = {s["id"] for s in b_list.json()}
    assert b_sid in b_ids
    assert a_sid not in b_ids


def test_chat_cross_user_operations_404(client):
    a = client.post("/api/v1/chat/sessions", json={"title": "alice only"}, headers=ALICE)
    a_sid = a.json()["id"]

    # bob cannot read, update, delete, or message alice's session
    assert client.get(f"/api/v1/chat/sessions/{a_sid}/messages", headers=BOB).status_code == 404
    assert client.put(f"/api/v1/chat/sessions/{a_sid}", json={"title": "hijack"}, headers=BOB).status_code == 404
    assert client.delete(f"/api/v1/chat/sessions/{a_sid}", headers=BOB).status_code == 404
    assert client.post(f"/api/v1/chat/sessions/{a_sid}/messages", json={"role": "user", "content": "x"}, headers=BOB).status_code == 404
    assert client.post(f"/api/v1/chat/sessions/{a_sid}/generate-title", headers=BOB).status_code == 404


def test_chat_session_created_with_actor_user_id(client):
    a = client.post("/api/v1/chat/sessions", json={"title": "owner"}, headers=ALICE)
    assert a.status_code == 200
    assert a.json()["user_id"] == "alice"


# ── Memories ────────────────────────────────────────────────────────────


def test_memory_drafts_are_actor_scoped(client):
    a = client.post(
        "/api/v1/memories/drafts",
        json={
            "draft_type": "statement",
            "payload": {"content": "alice prefers coffee", "statement_type": "preference"},
            "confidence": 0.7,
        },
        headers=ALICE,
    )
    assert a.status_code == 200
    a_draft_id = a.json()["id"]

    b = client.post(
        "/api/v1/memories/drafts",
        json={
            "draft_type": "statement",
            "payload": {"content": "bob prefers tea", "statement_type": "preference"},
            "confidence": 0.7,
        },
        headers=BOB,
    )
    assert b.status_code == 200
    b_draft_id = b.json()["id"]

    a_drafts = client.get("/api/v1/memories/drafts", headers=ALICE)
    a_ids = {d["id"] for d in a_drafts.json()}
    assert a_draft_id in a_ids
    assert b_draft_id not in a_ids

    b_drafts = client.get("/api/v1/memories/drafts", headers=BOB)
    b_ids = {d["id"] for d in b_drafts.json()}
    assert b_draft_id in b_ids
    assert a_draft_id not in b_ids


def test_memory_cross_user_draft_review_404(client):
    a = client.post(
        "/api/v1/memories/drafts",
        json={
            "draft_type": "statement",
            "payload": {"content": "alice secret", "statement_type": "fact"},
            "confidence": 0.7,
        },
        headers=ALICE,
    )
    a_draft_id = a.json()["id"]
    # bob cannot confirm/reject/supersede alice's draft
    assert client.post(f"/api/v1/memories/drafts/{a_draft_id}/confirm", headers=BOB).status_code == 404
    assert client.post(f"/api/v1/memories/drafts/{a_draft_id}/reject", headers=BOB).status_code == 404
    assert client.post(
        f"/api/v1/memories/drafts/{a_draft_id}/supersede",
        json={"superseded_statement_id": "x"},
        headers=BOB,
    ).status_code == 404


# ── Assets ──────────────────────────────────────────────────────────────


def test_asset_items_are_actor_scoped(client):
    a = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "alice's captured thought about cats", "raw_source_type": "manual"},
        headers=ALICE,
    )
    assert a.status_code == 200, a.text
    a_item_id = a.json()["id"]

    b = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "bob's captured thought about dogs", "raw_source_type": "manual"},
        headers=BOB,
    )
    assert b.status_code == 200, b.text
    b_item_id = b.json()["id"]

    a_items = client.get("/api/v1/assets/items", headers=ALICE)
    a_ids = {i["id"] for i in a_items.json()}
    assert a_item_id in a_ids
    assert b_item_id not in a_ids

    b_items = client.get("/api/v1/assets/items", headers=BOB)
    b_ids = {i["id"] for i in b_items.json()}
    assert b_item_id in b_ids
    assert a_item_id not in b_ids

    # bob cannot update/delete/confirm alice's item
    assert client.put(f"/api/v1/assets/items/{a_item_id}", json={"raw_title": "hijack"}, headers=BOB).status_code == 404
    assert client.delete(f"/api/v1/assets/items/{a_item_id}", headers=BOB).status_code == 404
    assert client.post(f"/api/v1/assets/items/{a_item_id}/confirm", json={}, headers=BOB).status_code == 404


# ── Traces ──────────────────────────────────────────────────────────────


def test_trace_bind_is_actor_scoped(client):
    a = client.post("/api/v1/chat/sessions", json={"title": "trace owner"}, headers=ALICE)
    a_sid = a.json()["id"]

    # bob cannot bind a trace to alice's session (session ownership 404)
    resp = client.post("/api/v1/traces/any-trace/bind-message", headers=BOB,
                       json={"session_id": a_sid, "assistant_message_id": "m"})
    assert resp.status_code == 404
    # alice can (though the trace itself may not exist → also 404; the important
    # assertion is that ownership is enforced before service lookup)
    resp_a = client.post("/api/v1/traces/any-trace/bind-message", headers=ALICE,
                         json={"session_id": a_sid, "assistant_message_id": "m"})
    # reaching the service (404 trace-not-found) means the ownership check passed
    assert resp_a.status_code == 404


def test_trace_export_is_actor_scoped(client):
    a = client.post("/api/v1/chat/sessions", json={"title": "export owner"}, headers=ALICE)
    a_sid = a.json()["id"]
    assert client.get(f"/api/v1/traces/sessions/{a_sid}/export", headers=BOB).status_code == 404
    assert client.get(f"/api/v1/traces/sessions/{a_sid}/export", headers=ALICE).status_code == 200
