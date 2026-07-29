from openai import OpenAI

from backend.app.config import settings


def test_embedding_connectivity():
    assert settings.EMBEDDING_API_BASE, "EMBEDDING_API_BASE is not configured"
    assert settings.EMBEDDING_API_KEY, "EMBEDDING_API_KEY or SILICONFLOW_API_KEY is not configured"
    assert settings.EMBEDDING_MODEL, "EMBEDDING_MODEL is not configured"

    client = OpenAI(
        base_url=settings.EMBEDDING_API_BASE,
        api_key=settings.EMBEDDING_API_KEY,
    )
    response = client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=["embedding connectivity test"],
    )

    embedding = response.data[0].embedding
    assert isinstance(embedding, list), "embedding response is not a list"
    assert embedding, "embedding response is empty"
    assert len(embedding) == settings.EMBEDDING_DIM, (
        f"embedding dimension mismatch: expected {settings.EMBEDDING_DIM}, got {len(embedding)}"
    )
