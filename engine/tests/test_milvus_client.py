from engine.app import milvus_client


def test_ensure_collection_connects_before_checking_collection(monkeypatch):
    calls = []

    class FakeUtility:
        @staticmethod
        def has_collection(name):
            calls.append(("has_collection", name))
            return True

    class FakeCollection:
        def __init__(self, name):
            calls.append(("collection", name))

    monkeypatch.setattr(milvus_client, "connect", lambda: calls.append(("connect", None)))
    monkeypatch.setattr(milvus_client, "utility", FakeUtility)
    monkeypatch.setattr(milvus_client, "Collection", FakeCollection)

    milvus_client.ensure_collection()

    assert calls[:2] == [
        ("connect", None),
        ("has_collection", milvus_client.COLLECTION_NAME),
    ]


def test_insert_vectors_batch_inserts_all_vectors(monkeypatch):
    insert_payloads = []

    class FakeCollection:
        def insert(self, payload):
            insert_payloads.append(payload)

    monkeypatch.setattr(milvus_client, "ensure_collection", lambda: FakeCollection())

    milvus_client.insert_vectors_batch([
        {"chunk_id": "chunk-1", "item_id": "item-1", "embedding": [0.1, 0.2]},
        {"chunk_id": "chunk-2", "item_id": "item-1", "embedding": [0.3, 0.4]},
    ])

    assert insert_payloads == [
        [
            ["chunk-1", "chunk-2"],
            [[0.1, 0.2], [0.3, 0.4]],
            ["chunk-1", "chunk-2"],
            ["item-1", "item-1"],
        ]
    ]


def test_delete_vectors_by_item_deletes_matching_item_and_flushes(monkeypatch):
    calls = []

    class FakeCollection:
        def delete(self, expr):
            calls.append(("delete", expr))

        def flush(self):
            calls.append(("flush", None))

    monkeypatch.setattr(milvus_client, "ensure_collection", lambda: FakeCollection())

    milvus_client.delete_vectors_by_item("item-1")

    assert calls == [
        ("delete", 'item_id == "item-1"'),
        ("flush", None),
    ]
