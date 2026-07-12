from engine.app import milvus_client


class FakeMilvusClient:
    def __init__(self):
        self.calls = []
        self.collections = set()
        self.search_results = [[
            {"entity": {"chunk_id": "chunk-1", "item_id": "item-1"}, "distance": 0.9},
        ]]

    def has_collection(self, name):
        self.calls.append(("has_collection", name))
        return name in self.collections

    def create_collection(self, **kwargs):
        self.calls.append(("create_collection", kwargs))
        self.collections.add(kwargs["collection_name"])

    def load_collection(self, collection_name, timeout=None):
        self.calls.append(("load_collection", collection_name, timeout))

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return self.search_results


def install_fake_client(monkeypatch):
    fake = FakeMilvusClient()
    monkeypatch.setattr(milvus_client, "_client", fake)
    return fake


def test_connect_returns_shared_milvus_client(monkeypatch):
    fake = install_fake_client(monkeypatch)

    assert milvus_client.connect() is fake


def test_ensure_collection_creates_missing_collection(monkeypatch):
    fake = install_fake_client(monkeypatch)

    milvus_client.ensure_collection()

    assert fake.calls[0] == ("has_collection", milvus_client.COLLECTION_NAME)
    assert fake.calls[1][0] == "create_collection"
    assert fake.calls[1][1]["collection_name"] == milvus_client.COLLECTION_NAME


def test_insert_vectors_batch_inserts_rows_with_milvus_client_shape(monkeypatch):
    fake = install_fake_client(monkeypatch)
    fake.collections.add(milvus_client.COLLECTION_NAME)

    milvus_client.insert_vectors_batch([
        {"chunk_id": "chunk-1", "item_id": "item-1", "embedding": [0.1, 0.2]},
        {"chunk_id": "chunk-2", "item_id": "item-1", "embedding": [0.3, 0.4]},
    ])

    assert fake.calls[-1] == (
        "insert",
        {
            "collection_name": milvus_client.COLLECTION_NAME,
            "data": [
                {"id": "chunk-1", "chunk_id": "chunk-1", "item_id": "item-1", "embedding": [0.1, 0.2]},
                {"id": "chunk-2", "chunk_id": "chunk-2", "item_id": "item-1", "embedding": [0.3, 0.4]},
            ],
        },
    )


def test_delete_vectors_by_ids_deletes_primary_keys_without_loading_collection(monkeypatch):
    fake = install_fake_client(monkeypatch)
    fake.collections.add(milvus_client.COLLECTION_NAME)

    milvus_client.delete_vectors_by_ids(["chunk-1", "chunk-2"])

    assert not any(call[0] == "load_collection" for call in fake.calls)
    assert fake.calls[-1] == (
        "delete",
        {
            "collection_name": milvus_client.COLLECTION_NAME,
            "ids": ["chunk-1", "chunk-2"],
            "timeout": milvus_client.MILVUS_OPERATION_TIMEOUT_SECONDS,
        },
    )


def test_delete_vectors_by_item_loads_collection_with_timeout_before_delete(monkeypatch):
    fake = install_fake_client(monkeypatch)
    fake.collections.add(milvus_client.COLLECTION_NAME)

    milvus_client.delete_vectors_by_item("item-1")

    load_call = ("load_collection", milvus_client.COLLECTION_NAME, milvus_client.MILVUS_OPERATION_TIMEOUT_SECONDS)
    assert load_call in fake.calls
    assert fake.calls.index(load_call) < len(fake.calls) - 1
    assert fake.calls[-1] == (
        "delete",
        {
            "collection_name": milvus_client.COLLECTION_NAME,
            "filter": 'item_id == "item-1"',
            "timeout": milvus_client.MILVUS_OPERATION_TIMEOUT_SECONDS,
        },
    )


def test_search_vectors_loads_collection_with_timeout_before_search(monkeypatch):
    fake = install_fake_client(monkeypatch)
    fake.collections.add(milvus_client.COLLECTION_NAME)

    hits = milvus_client.search_vectors([0.1, 0.2], top_k=3)

    load_call = ("load_collection", milvus_client.COLLECTION_NAME, milvus_client.MILVUS_OPERATION_TIMEOUT_SECONDS)
    assert load_call in fake.calls
    assert fake.calls[-1][0] == "search"
    assert fake.calls.index(load_call) < len(fake.calls) - 1
    assert fake.calls[-1][1]["timeout"] == milvus_client.MILVUS_OPERATION_TIMEOUT_SECONDS
    assert hits == [{"chunk_id": "chunk-1", "item_id": "item-1", "score": 0.9}]
