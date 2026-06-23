import uuid
from typing import Any

from openai import OpenAI
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from backend.app.config import settings
from backend.app.models.memory import MemoryEntry, MemoryStatement

MEMORY_COLLECTION_NAME = "prism_memory"
KIND_ENTRY = "entry"
KIND_STATEMENT = "statement"
_embedding_client: OpenAI | None = None


def _connect_milvus() -> None:
    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)


def ensure_memory_collection() -> Collection:
    _connect_milvus()
    if utility.has_collection(MEMORY_COLLECTION_NAME):
        return Collection(MEMORY_COLLECTION_NAME)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="memory_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="kind", dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=64),
    ]
    schema = CollectionSchema(fields, description="Prism long-term memory vectors")
    collection = Collection(MEMORY_COLLECTION_NAME, schema)
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


def _entry_vector_text(entry: MemoryEntry) -> str:
    parts = [entry.title or "", entry.content or "", entry.category or "", entry.memory_type or ""]
    return "\n".join(part for part in parts if part)


def _statement_vector_text(statement: MemoryStatement) -> str:
    parts = [statement.content or "", statement.statement_type or "", statement.temporal_type or ""]
    return "\n".join(part for part in parts if part)


def upsert_entry_vector(entry: MemoryEntry) -> str:
    return _upsert(KIND_ENTRY, entry.id, entry.user_id, entry.memory_type or "",
                   entry.embedding_ref, _entry_vector_text(entry))


def upsert_statement_vector(statement: MemoryStatement) -> str:
    return _upsert(KIND_STATEMENT, statement.id, statement.user_id, statement.statement_type or "",
                   statement.embedding_ref, _statement_vector_text(statement))


def _upsert(kind: str, memory_id: str, user_id: str, memory_type: str,
            embedding_ref: str, text: str) -> str:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return ""
    if not (text or "").strip():
        return ""
    embedding = embed_text(text)
    vector_id = embedding_ref or f"memory-{uuid.uuid4()}"
    collection = ensure_memory_collection()
    if embedding_ref:
        collection.delete(expr=f'id == "{embedding_ref}"')
    collection.insert(
        [
            [vector_id],
            [embedding],
            [memory_id],
            [user_id or "default-user"],
            [kind],
            [memory_type or ""],
        ]
    )
    collection.flush()
    return vector_id


def delete_memory_vector(embedding_ref: str) -> None:
    if not embedding_ref:
        return
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return
    try:
        collection = ensure_memory_collection()
        collection.delete(expr=f'id == "{embedding_ref}"')
        collection.flush()
    except Exception:
        pass


def search_memory_vectors(
    *,
    text: str,
    user_id: str = "default-user",
    top_k: int = 20,
) -> list[dict[str, Any]]:
    if not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return []
    if not (text or "").strip():
        return []
    embedding = embed_text(text)
    collection = ensure_memory_collection()
    collection.load()
    expr = f'user_id == "{user_id}"'
    results = collection.search(
        data=[embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=top_k,
        expr=expr,
        output_fields=["memory_id", "user_id", "kind", "memory_type"],
    )
    return [
        {
            "memory_id": hit.entity.get("memory_id"),
            "kind": hit.entity.get("kind"),
            "memory_type": hit.entity.get("memory_type"),
            "score": float(hit.score),
        }
        for hit in results[0]
    ]
