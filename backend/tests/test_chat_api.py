# prism/backend/tests/test_chat_api.py


def test_create_session_and_list(client):
    resp = client.post("/api/v1/chat/sessions", json={"title": "RAG 讨论"})
    assert resp.status_code == 200
    session = resp.json()
    assert session["title"] == "RAG 讨论"

    resp2 = client.get("/api/v1/chat/sessions")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


def test_add_and_list_messages(client):
    s = client.post("/api/v1/chat/sessions", json={"title": "测试"})
    sid = s.json()["id"]

    client.post(f"/api/v1/chat/sessions/{sid}/messages",
                json={"role": "user", "content": "你好"})
    client.post(f"/api/v1/chat/sessions/{sid}/messages",
                json={"role": "assistant", "content": "你好！有什么可以帮你的？",
                      "sources": ["chunk-1"]})

    resp = client.get(f"/api/v1/chat/sessions/{sid}/messages")
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["sources"] == ["chunk-1"]


def test_update_message_replaces_pending_assistant_placeholder(client):
    s = client.post("/api/v1/chat/sessions", json={"title": "pending"})
    sid = s.json()["id"]

    created = client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"role": "assistant", "content": ""},
    )
    assert created.status_code == 200
    msg_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/chat/sessions/{sid}/messages/{msg_id}",
        json={
            "content": "完整回答",
            "sources": ["chunk-1"],
            "clarify": {"question": "需要补充吗", "options": []},
            "process": {
                "agent_status": "generating answer",
                "tool_runs": [{"id": "run-1", "tool": "knowledge_search", "query": "q", "status": "success"}],
                "thinking_steps": [{"label": "检索知识库", "status": "success"}],
            },
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == msg_id
    assert body["content"] == "完整回答"
    assert body["sources"] == ["chunk-1"]
    assert body["clarify"]["question"] == "需要补充吗"
    assert body["process"]["agent_status"] == "generating answer"
    assert body["process"]["tool_runs"][0]["tool"] == "knowledge_search"

    listed = client.get(f"/api/v1/chat/sessions/{sid}/messages")
    assert listed.status_code == 200
    assert listed.json()[0]["process"]["thinking_steps"][0]["label"] == "检索知识库"


def test_add_message_nonexistent_session_404(client):
    resp = client.post("/api/v1/chat/sessions/nope/messages",
                       json={"role": "user", "content": "x"})
    assert resp.status_code == 404
