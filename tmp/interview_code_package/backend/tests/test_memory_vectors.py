from backend.app.models.memory import MemoryEntry, MemoryStatement
from backend.app.services import memory_vectors


def test_memory_vectors_use_dedicated_collection(monkeypatch):
    created = {}

    class FakeUtility:
        @staticmethod
        def has_collection(name):
            created["has_collection_name"] = name
            return False

    class FakeCollection:
        def __init__(self, name, schema):
            created["collection_name"] = name

        def create_index(self, field_name, index_params):
            created["index_params"] = index_params

    monkeypatch.setattr(memory_vectors.connections, "connect", lambda **kwargs: None)
    monkeypatch.setattr(memory_vectors, "utility", FakeUtility)
    monkeypatch.setattr(memory_vectors, "Collection", FakeCollection)

    memory_vectors.ensure_memory_collection()

    assert created["has_collection_name"] == "prism_memory"
    assert created["collection_name"] == "prism_memory"
    assert created["index_params"]["metric_type"] == "COSINE"


def test_upsert_entry_vector_inserts_and_returns_id(monkeypatch):
    calls = []

    class FakeCollection:
        def insert(self, rows):
            calls.append(("insert", rows))

        def flush(self):
            calls.append(("flush",))

        def delete(self, expr=None):
            calls.append(("delete", expr))

    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(memory_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(memory_vectors, "ensure_memory_collection", lambda: FakeCollection())

    entry = MemoryEntry(
        id="entry-1",
        user_id="default-user",
        title="偏好深色主题",
        content="用户偏好深色主题阅读。",
        memory_type="preference",
        importance=0.8,
    )

    vector_id = memory_vectors.upsert_entry_vector(entry)

    assert vector_id.startswith("memory-")
    insert_rows = next(c[1] for c in calls if c[0] == "insert")
    assert insert_rows[0] == [vector_id]
    assert insert_rows[2] == ["entry-1"]
    assert insert_rows[4] == ["entry"]


def test_upsert_statement_vector_reuses_existing_ref(monkeypatch):
    calls = []

    class FakeCollection:
        def insert(self, rows):
            calls.append(("insert", rows))

        def flush(self):
            calls.append(("flush",))

        def delete(self, expr=None):
            calls.append(("delete", expr))

    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(memory_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(memory_vectors, "ensure_memory_collection", lambda: FakeCollection())

    statement = MemoryStatement(
        id="stmt-1",
        user_id="default-user",
        content="用户每天早上复习知识。",
        statement_type="habit",
        embedding_ref="existing-ref",
    )

    vector_id = memory_vectors.upsert_statement_vector(statement)

    assert vector_id == "existing-ref"
    delete_calls = [c[1] for c in calls if c[0] == "delete"]
    assert delete_calls == ['id == "existing-ref"']
    insert_rows = next(c[1] for c in calls if c[0] == "insert")
    assert insert_rows[4] == ["statement"]


def test_upsert_returns_empty_when_embedding_not_configured(monkeypatch):
    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_BASE", "")
    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_KEY", "")

    entry = MemoryEntry(id="e1", user_id="default-user", title="t", content="c")

    assert memory_vectors.upsert_entry_vector(entry) == ""


def test_search_memory_vectors_returns_scored_hits(monkeypatch):
    class FakeHit:
        def __init__(self, memory_id, kind, memory_type, score):
            self.score = score
            self.entity = {
                "memory_id": memory_id,
                "kind": kind,
                "memory_type": memory_type,
                "user_id": "default-user",
            }

    class FakeResults:
        def __init__(self, rows):
            self._rows = rows

        def __getitem__(self, idx):
            return self._rows

    class FakeCollection:
        def load(self):
            pass

        def search(self, **kwargs):
            return FakeResults([FakeHit("m1", "entry", "preference", 0.91)])

    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(memory_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(memory_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(memory_vectors, "ensure_memory_collection", lambda: FakeCollection())

    hits = memory_vectors.search_memory_vectors(text="深色主题", user_id="default-user", top_k=5)

    assert len(hits) == 1
    assert hits[0]["memory_id"] == "m1"
    assert hits[0]["kind"] == "entry"
    assert abs(hits[0]["score"] - 0.91) < 1e-6
