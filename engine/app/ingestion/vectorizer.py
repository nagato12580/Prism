# prism/engine/app/ingestion/vectorizer.py
"""Embedding API wrapper for ingestion and retrieval."""

from collections.abc import Iterator

from openai import OpenAI

from ..config import settings

_client = None


class EmbeddingProviderError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.EMBEDDING_API_BASE,
            api_key=settings.EMBEDDING_API_KEY,
            timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
            max_retries=settings.EMBEDDING_MAX_RETRIES,
        )
    return _client


def _batches(texts: list[str], size: int) -> Iterator[list[str]]:
    batch_size = max(1, size)
    for start in range(0, len(texts), batch_size):
        yield texts[start : start + batch_size]


def embed_texts(texts: list[str], *, timeout: float | None = None) -> list[list[float]]:
    """Embed texts in bounded batches and preserve input order."""
    if not texts:
        return []

    client = _get_client()
    if timeout is not None:
        client = client.with_options(timeout=timeout, max_retries=0)
    embeddings: list[list[float]] = []
    batches = list(_batches(texts, settings.EMBEDDING_BATCH_SIZE))

    for index, batch in enumerate(batches, start=1):
        try:
            kwargs = {"model": settings.EMBEDDING_MODEL, "input": batch}
            resp = client.embeddings.create(**kwargs)
        except Exception as exc:
            raise EmbeddingProviderError(
                "Embedding request failed "
                f"(endpoint={settings.EMBEDDING_API_BASE}, "
                f"model={settings.EMBEDDING_MODEL}, "
                f"batch {index}/{len(batches)}, "
                f"batch_size={len(batch)}): {exc}"
            ) from exc
        embeddings.extend(item.embedding for item in resp.data)

    return embeddings


def embed_query(text: str, *, timeout: float | None = None) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text], timeout=timeout)[0]
