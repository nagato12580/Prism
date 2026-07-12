import uuid
from typing import Any

from openai import OpenAI
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from backend.app.config import settings
from backend.app.models.knowledge_governance import CanonicalKnowledgePoint


CKP_COLLECTION_NAME = "prism_ckp"
_embedding_client: OpenAI | None = None


def _connect_milvus() -> None:
    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)


def ensure_ckp_collection() -> Collection:
    _connect_milvus()
    if utility.has_collection(CKP_COLLECTION_NAME):
        return Collection(CKP_COLLECTION_NAME)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="ckp_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="canonical_type", dtype=DataType.VARCHAR, max_length=64),
    ]
    schema = CollectionSchema(fields, description="Prism canonical knowledge point vectors")
    collection = Collection(CKP_COLLECTION_NAME, schema)
    collection.create_index(
        field_name="embedding",
        index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
    )
    return collection


def _get_embedding_client() -> OpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(base_url=settings.EMBEDDING_API_BASE, api_key=settings.EMBEDDING_API_KEY)
    return _embedding_client


def embed_text(text: str) -> list[float]:
    client = _get_embedding_client()
    response = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=[text])
    return response.data[0].embedding


def _ckp_vector_text(ckp: CanonicalKnowledgePoint) -> str:
    parts: list[str] = [
        ckp.title or "",
        ckp.canonical_statement or "",
        ckp.summary or "",
        " ".join(str(item) for item in (ckp.keywords or [])),
        " ".join(str(item) for item in (ckp.concepts or [])),
    ]
    return "\n".join(part for part in parts if part)


def upsert_ckp_vector(ckp: CanonicalKnowledgePoint) -> str:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return ""
    embedding = embed_text(_ckp_vector_text(ckp))
    vector_id = ckp.embedding_ref or f"ckp-{uuid.uuid4()}"
    collection = ensure_ckp_collection()
    if ckp.embedding_ref:
        collection.delete(expr=f'id == "{ckp.embedding_ref}"')
    collection.insert(
        [
            [vector_id],
            [embedding],
            [ckp.id],
            [ckp.user_id],
            [ckp.canonical_type or ""],
        ]
    )
    collection.flush()
    return vector_id


def search_ckp_vectors(*, text: str, user_id: str, canonical_type: str = "", top_k: int = 8) -> list[dict[str, Any]]:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return []
    embedding = embed_text(text)
    collection = ensure_ckp_collection()
    collection.load()
    expr = f'user_id == "{user_id}"'
    if canonical_type:
        expr += f' && canonical_type == "{canonical_type}"'
    results = collection.search(
        data=[embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=top_k,
        expr=expr,
        output_fields=["ckp_id", "user_id", "canonical_type"],
    )
    return [
        {
            "ckp_id": hit.entity.get("ckp_id"),
            "score": float(hit.score),
            "user_id": hit.entity.get("user_id"),
            "canonical_type": hit.entity.get("canonical_type"),
        }
        for hit in results[0]
    ]
