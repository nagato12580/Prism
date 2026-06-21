def test_ckp_vectors_use_dedicated_collection(monkeypatch):
    from backend.app.services import ckp_vectors

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

    monkeypatch.setattr(ckp_vectors.connections, "connect", lambda **kwargs: None)
    monkeypatch.setattr(ckp_vectors, "utility", FakeUtility)
    monkeypatch.setattr(ckp_vectors, "Collection", FakeCollection)

    ckp_vectors.ensure_ckp_collection()

    assert created["has_collection_name"] == "prism_ckp"
    assert created["collection_name"] == "prism_ckp"
    assert created["collection_name"] != "prism_knowledge"
    assert created["index_params"]["metric_type"] == "COSINE"


def test_upsert_ckp_vector_flushes_collection(monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import ckp_vectors

    calls = []

    class FakeCollection:
        def insert(self, rows):
            calls.append(("insert", rows))

        def flush(self):
            calls.append(("flush", None))

    monkeypatch.setattr(ckp_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(ckp_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(ckp_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(ckp_vectors, "ensure_ckp_collection", lambda: FakeCollection())

    ckp = CanonicalKnowledgePoint(
        id="ckp-1",
        user_id="user-1",
        canonical_type="claim",
        title="Test CKP",
        canonical_statement="A CKP vector should become searchable after upsert.",
        keywords=["vector"],
    )

    vector_ref = ckp_vectors.upsert_ckp_vector(ckp)

    assert vector_ref.startswith("ckp-")
    assert [call[0] for call in calls] == ["insert", "flush"]
