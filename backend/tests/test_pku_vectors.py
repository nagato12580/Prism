def test_pku_vectors_use_dedicated_collection(monkeypatch):
    from backend.app.services import pku_vectors

    created = {}

    class FakeUtility:
        @staticmethod
        def has_collection(name):
            created["has_collection_name"] = name
            return False

    class FakeCollection:
        def __init__(self, name, schema):
            created["collection_name"] = name
            created["schema"] = schema

        def create_index(self, field_name, index_params):
            created["index_field"] = field_name
            created["index_params"] = index_params

    monkeypatch.setattr(pku_vectors.connections, "connect", lambda **kwargs: None)
    monkeypatch.setattr(pku_vectors, "utility", FakeUtility)
    monkeypatch.setattr(pku_vectors, "Collection", FakeCollection)

    pku_vectors.ensure_pku_collection()

    assert created["has_collection_name"] == "prism_pku"
    assert created["collection_name"] == "prism_pku"
    assert created["index_params"]["metric_type"] == "COSINE"


def test_upsert_pku_vector_flushes_collection(monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import pku_vectors

    calls = []

    class FakeCollection:
        def insert(self, rows):
            calls.append(("insert", rows))

        def flush(self):
            calls.append(("flush", None))

    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(pku_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pku_vectors, "ensure_pku_collection", lambda: FakeCollection())

    pku = PersonalKnowledgeUnit(
        id="pku-1",
        user_id="user-1",
        source_kind="document_chunk",
        source_id="chunk-1",
        unit_type="claim",
        statement="Database table storage engine must use InnoDB.",
        normalized_statement="database table storage engine must use innodb",
        normalized_statement_hash="hash-1",
        evidence_span="storage engine must use InnoDB",
        keywords=["database", "innodb"],
        concepts=["storage engine"],
    )

    vector_ref = pku_vectors.upsert_pku_vector(pku)

    assert vector_ref.startswith("pku-")
    assert [call[0] for call in calls] == ["insert", "flush"]
    inserted_rows = calls[0][1]
    assert inserted_rows[2] == ["pku-1"]
    assert inserted_rows[3] == ["user-1"]
    assert inserted_rows[4] == ["claim"]
    assert inserted_rows[5] == ["document_chunk"]
    assert inserted_rows[6] == ["chunk-1"]


def test_search_pku_vectors_filters_by_user_unit_type_and_source_kind(monkeypatch):
    from backend.app.services import pku_vectors

    captured = {}

    class FakeEntity:
        def __init__(self):
            self.data = {
                "pku_id": "pku-1",
                "user_id": "user-1",
                "unit_type": "claim",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
            }

        def get(self, key):
            return self.data[key]

    class FakeHit:
        score = 0.88
        entity = FakeEntity()

    class FakeCollection:
        def load(self):
            captured["loaded"] = True

        def search(self, **kwargs):
            captured["expr"] = kwargs["expr"]
            return [[FakeHit()]]

    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(pku_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pku_vectors, "ensure_pku_collection", lambda: FakeCollection())

    hits = pku_vectors.search_pku_vectors(
        text="database engine",
        user_id="user-1",
        unit_type="claim",
        source_kind="document_chunk",
        top_k=5,
    )

    assert 'user_id == "user-1"' in captured["expr"]
    assert 'unit_type == "claim"' in captured["expr"]
    assert 'source_kind == "document_chunk"' in captured["expr"]
    assert hits == [
        {
            "pku_id": "pku-1",
            "score": 0.88,
            "user_id": "user-1",
            "unit_type": "claim",
            "source_kind": "document_chunk",
            "source_id": "chunk-1",
        }
    ]
