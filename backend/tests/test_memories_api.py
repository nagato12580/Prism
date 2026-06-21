from backend.app.models import MemoryEntry


def test_list_memories_returns_user_memories_ordered_by_importance(client, db_session):
    db_session.add_all(
        [
            MemoryEntry(
                user_id="default-user",
                title="Prefers concise engineering updates",
                content="The user likes direct implementation notes with verification evidence.",
                memory_type="preference",
                category="communication",
                tags=["updates", "verification"],
                importance=0.9,
            ),
            MemoryEntry(
                user_id="default-user",
                title="Building Prism",
                content="The current project is a personal knowledge workspace.",
                memory_type="context",
                category="project",
                tags=["prism"],
                importance=0.6,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/memories")

    assert response.status_code == 200
    payload = response.json()
    assert [item["title"] for item in payload] == [
        "Prefers concise engineering updates",
        "Building Prism",
    ]
    assert payload[0]["memory_type"] == "preference"
    assert payload[0]["tags"] == ["updates", "verification"]


def test_list_memories_filters_by_memory_type(client, db_session):
    db_session.add_all(
        [
            MemoryEntry(
                user_id="default-user",
                title="Goal memory",
                content="Ship a reliable knowledge asset workflow.",
                memory_type="goal",
                importance=0.8,
            ),
            MemoryEntry(
                user_id="default-user",
                title="Fact memory",
                content="The app uses React and FastAPI.",
                memory_type="fact",
                importance=0.7,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/memories?memory_type=goal")

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Goal memory"]
