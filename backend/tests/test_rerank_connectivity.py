import requests

from backend.app.config import settings


def test_rerank_connectivity():
    assert settings.RERANK_API_BASE, "RERANK_API_BASE is not configured"
    assert settings.EMBEDDING_API_KEY, "EMBEDDING_API_KEY or SILICONFLOW_API_KEY is not configured"
    assert settings.RERANK_MODEL, "RERANK_MODEL is not configured"

    response = requests.post(
        settings.RERANK_API_BASE,
        headers={
            "Authorization": f"Bearer {settings.EMBEDDING_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.RERANK_MODEL,
            "query": "苹果水果",
            "documents": [
                "苹果是一种水果",
                "汽车需要加油",
                "向量检索可以配合重排序",
            ],
            "return_documents": True,
            "top_n": 3,
        },
        timeout=30,
    )
    assert response.status_code == 200, (
        f"rerank request failed: status={response.status_code}, body={response.text[:500]}"
    )

    payload = response.json()
    results = payload.get("results")
    assert isinstance(results, list), f"rerank results is not a list: {payload}"
    assert results, f"rerank results is empty: {payload}"
    assert results[0]["index"] == 0, f"unexpected rerank order: {payload}"
