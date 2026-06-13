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


def test_add_message_nonexistent_session_404(client):
    resp = client.post("/api/v1/chat/sessions/nope/messages",
                       json={"role": "user", "content": "x"})
    assert resp.status_code == 404
