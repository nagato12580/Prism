import uuid
from typing import Any

from openai import OpenAI
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from backend.app.config import settings
from backend.app.models.knowledge_governance import PersonalKnowledgeUnit


PKU_COLLECTION_NAME = "prism_pku"
_embedding_client: OpenAI | None = None


def _connect_milvus() -> None:
    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)


def ensure_pku_collection() -> Collection:
    _connect_milvus()
    if utility.has_collection(PKU_COLLECTION_NAME):
        return Collection(PKU_COLLECTION_NAME)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="pku_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="unit_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="source_kind", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="source_id", dtype=DataType.VARCHAR, max_length=64),
    ]
    schema = CollectionSchema(fields, description="Prism personal knowledge unit vectors")
    collection = Collection(PKU_COLLECTION_NAME, schema)
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


def _list_text(items: Any) -> str:
    if not items:
        return ""
    if isinstance(items, list):
        return " ".join(str(item) for item in items if item)
    return str(items)


def _pku_vector_text(pku: PersonalKnowledgeUnit) -> str:
    parts = [
        pku.statement or "",
        pku.normalized_statement or "",
        pku.evidence_span or "",
        pku.subject or "",
        pku.predicate or "",
        pku.object or "",
        _list_text(pku.keywords),
        _list_text(pku.concepts),
        _list_text(pku.entities),
        _list_text(pku.domains),
        pku.unit_type or "",
        pku.source_kind or "",
    ]
    return "\n".join(part for part in parts if part)


def upsert_pku_vector(pku: PersonalKnowledgeUnit) -> str:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return ""
    embedding = embed_text(_pku_vector_text(pku))
    vector_id = pku.embedding_ref or f"pku-{uuid.uuid4()}"
    collection = ensure_pku_collection()
    if pku.embedding_ref:
        collection.delete(expr=f'id == "{pku.embedding_ref}"')
    collection.insert(
        [
            [vector_id],
            [embedding],
            [pku.id],
            [pku.user_id],
            [pku.unit_type or ""],
            [pku.source_kind or ""],
            [pku.source_id or ""],
        ]
    )
    collection.flush()
    return vector_id


def search_pku_vectors(
    *,
    text: str,
    user_id: str,
    unit_type: str = "",
    source_kind: str = "",
    top_k: int = 20,
) -> list[dict[str, Any]]:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return []
    embedding = embed_text(text)
    collection = ensure_pku_collection()
    collection.load()
    expr = f'user_id == "{user_id}"'
    if unit_type:
        expr += f' && unit_type == "{unit_type}"'
    if source_kind:
        expr += f' && source_kind == "{source_kind}"'
    results = collection.search(
        data=[embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=top_k,
        expr=expr,
        output_fields=["pku_id", "user_id", "unit_type", "source_kind", "source_id"],
    )
    return [
        {
            "pku_id": hit.entity.get("pku_id"),
            "score": float(hit.score),
            "user_id": hit.entity.get("user_id"),
            "unit_type": hit.entity.get("unit_type"),
            "source_kind": hit.entity.get("source_kind"),
            "source_id": hit.entity.get("source_id"),
        }
        for hit in results[0]
    ]
