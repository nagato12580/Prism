import pytest

from engine.app.ingestion import vectorizer


class _FakeEmbedding:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embeddings):
        self.data = [_FakeEmbedding(embedding) for embedding in embeddings]


def test_embed_texts_batches_requests_and_preserves_order(monkeypatch):
    calls = []

    class FakeEmbeddings:
        def create(self, *, model, input):
            calls.append({"model": model, "input": list(input)})
            return _FakeEmbeddingResponse([[float(len(calls)), float(i)] for i, _ in enumerate(input)])

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(vectorizer.settings, "EMBEDDING_BATCH_SIZE", 2)
    monkeypatch.setattr(vectorizer.settings, "EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setattr(vectorizer, "_get_client", lambda: FakeClient())

    embeddings = vectorizer.embed_texts(["a", "b", "c", "d", "e"])

    assert [call["input"] for call in calls] == [["a", "b"], ["c", "d"], ["e"]]
    assert all(call["model"] == "test-embedding" for call in calls)
    assert embeddings == [[1.0, 0.0], [1.0, 1.0], [2.0, 0.0], [2.0, 1.0], [3.0, 0.0]]


def test_embed_texts_wraps_provider_timeout_with_context(monkeypatch):
    class FakeEmbeddings:
        def create(self, *, model, input):
            raise TimeoutError("Request timed out.")

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(vectorizer.settings, "EMBEDDING_BATCH_SIZE", 10)
    monkeypatch.setattr(vectorizer.settings, "EMBEDDING_MODEL", "test-embedding")
    monkeypatch.setattr(vectorizer.settings, "EMBEDDING_API_BASE", "https://embedding.example/v1")
    monkeypatch.setattr(vectorizer, "_get_client", lambda: FakeClient())

    with pytest.raises(vectorizer.EmbeddingProviderError) as exc_info:
        vectorizer.embed_texts(["hello"])

    message = str(exc_info.value)
    assert "Embedding request failed" in message
    assert "https://embedding.example/v1" in message
    assert "test-embedding" in message
    assert "batch 1/1" in message
    assert "Request timed out." in message
