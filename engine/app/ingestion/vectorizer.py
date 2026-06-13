# prism/engine/app/ingestion/vectorizer.py
"""调用 embedding API 将文本转为向量。"""
from openai import OpenAI
from ..config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(base_url=settings.EMBEDDING_API_BASE, api_key=settings.EMBEDDING_API_KEY)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。"""
    client = _get_client()
    resp = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def embed_query(text: str) -> list[float]:
    """单条查询向量化。"""
    return embed_texts([text])[0]
