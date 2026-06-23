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
