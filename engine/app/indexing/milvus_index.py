# engine/app/indexing/milvus_index.py
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from pymilvus import Collection, connections, utility

from engine.app.indexing.profiles import EmbeddingProfile, DEFAULT_PROFILE


def _literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _scope_expr(scope) -> str:
    return (
        f'tenant_id == "{_literal(scope.tenant_id)}" and '
        f'kb_uid == "{_literal(scope.kb_uid)}" and '
        f'generation == "{_literal(scope.generation)}"'
    )


def _retrieval_scope_expr(scope) -> str:
    parts = [
        f'tenant_id == "{_literal(scope.tenant_id)}"',
        f'kb_uid == "{_literal(scope.kb_uid)}"',
        f'generation == "{_literal(scope.index_generation)}"',
    ]
    if scope.file_uids:
        values = ", ".join(f'"{_literal(value)}"' for value in scope.file_uids)
        parts.append(f"file_uid in [{values}]")
    if scope.source_types:
        values = ", ".join(f'"{_literal(value)}"' for value in scope.source_types)
        parts.append(f"source_type in [{values}]")
    return " and ".join(parts)


def search_index(*, query_embedding, scope, top_k, timeout=15):
    """Search the generation collection with server-side tenant/KB filters."""
    collection_name = os.getenv("PRISM_RETRIEVAL_MILVUS_COLLECTION")
    if collection_name:
        _connect()
        collection = Collection(collection_name)
        collection.load(timeout=min(30, timeout))
    else:
        collection = ensure_collection(load_timeout=timeout)
    rows = collection.search(
        data=[query_embedding],
        anns_field="embedding",
        param={"metric_type": DEFAULT_PROFILE.metric, "params": {"nprobe": 32}},
        limit=top_k,
        expr=_retrieval_scope_expr(scope),
        output_fields=["chunk_uid", "item_id", "file_uid", "kb_uid", "source_type", "content"],
        timeout=min(15, timeout),
    )
    results = []
    for hit in rows[0] if rows else []:
        entity = getattr(hit, "entity", None) or hit.get("entity", hit)
        get = entity.get if hasattr(entity, "get") else lambda key, default=None: getattr(entity, key, default)
        score = getattr(hit, "distance", None)
        if score is None and hasattr(hit, "get"):
            score = hit.get("distance", hit.get("score", 0.0))
        results.append({
            "chunk_uid": get("chunk_uid"), "item_id": get("item_id"),
            "file_uid": get("file_uid"), "kb_uid": get("kb_uid"),
            "source_type": get("source_type"), "content": get("content"),
            "score": float(score or 0.0),
        })
    return results


class MilvusGenerationIndex:
    def __init__(self, collection):
        self.collection = collection

    def write(self, rows):
        if not rows:
            return 0
        fields = (
            "tenant_id", "kb_uid", "file_uid", "item_id", "chunk_uid",
            "source_type", "generation", "embedding_model_version", "content",
            "indexed_at", "embedding",
        )
        schema = getattr(self.collection, "schema", None)
        schema_fields = {field.name for field in schema.fields} if schema else set(fields)
        payload = [
            {
                "id": f'{row["chunk_uid"]}:{row["generation"]}',
                **{field: row[field] for field in fields if field in schema_fields},
            }
            for row in rows
        ]
        self.collection.insert(payload, timeout=15)
        self.collection.flush(timeout=15)
        return len(rows)

    def count(self, scope):
        result = self.collection.query(
            expr=_scope_expr(scope), output_fields=["count(*)"], timeout=15
        )
        return int(result[0].get("count(*)", 0)) if result else 0

    def sample(self, scope, chunk_uid):
        result = self.collection.query(
            expr=f'{_scope_expr(scope)} and chunk_uid == "{_literal(chunk_uid)}"',
            output_fields=["chunk_uid"],
            limit=1,
            timeout=15,
        )
        return bool(result)

    def delete_generation(self, scope):
        result = self.collection.delete(_scope_expr(scope), timeout=15)
        self.collection.flush(timeout=15)
        return result

    def delete_file(self, tenant_id, kb_uid, file_uid):
        expr = (
            f'tenant_id == "{_literal(tenant_id)}" and '
            f'kb_uid == "{_literal(kb_uid)}" and '
            f'file_uid == "{_literal(file_uid)}"'
        )
        result = self.collection.delete(expr, timeout=15)
        self.collection.flush(timeout=15)
        return result


def _connect(host: str = "127.0.0.1", port: int = 19530):
    try:
        if not connections.has_connection("default"):
            connections.connect("default", host=host, port=port)
    except Exception:
        raise RuntimeError("MILVUS_UNAVAILABLE")


def ensure_collection(
    profile: EmbeddingProfile | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 19530,
    load_timeout: float = 30,
):
    profile = profile or DEFAULT_PROFILE
    _connect(host, port)
    if utility.has_collection(profile.collection_name):
        collection = Collection(profile.collection_name)
        collection.load(timeout=min(30, load_timeout))
        return collection
    from pymilvus import CollectionSchema, DataType, FieldSchema
    fields = [
        FieldSchema("id", DataType.VARCHAR, max_length=100, is_primary=True),
        FieldSchema("tenant_id", DataType.VARCHAR, max_length=36),
        FieldSchema("kb_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("file_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("item_id", DataType.VARCHAR, max_length=36),
        FieldSchema("chunk_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("source_type", DataType.VARCHAR, max_length=32),
        FieldSchema("generation", DataType.VARCHAR, max_length=36),
        FieldSchema("embedding_model_version", DataType.VARCHAR, max_length=32),
        FieldSchema("indexed_at", DataType.VARCHAR, max_length=40),
        FieldSchema("content", DataType.VARCHAR, max_length=65535),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=profile.dimension),
    ]
    schema = CollectionSchema(fields, description="Prism knowledge chunks")
    collection = Collection(profile.collection_name, schema, timeout=min(15, load_timeout))
    index_params = {
        "metric_type": profile.metric,
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index("embedding", index_params, timeout=min(30, load_timeout))
    collection.load(timeout=min(30, load_timeout))
    return collection


def write_chunks(
    collection,
    kb_uid: str,
    file_uid: str,
    generation: str,
    chunks: list[dict],
):
    if not chunks:
        return
    data = []
    for chunk in chunks:
        data.append({
            "id": f"{chunk['chunk_uid']}:{generation}",
            "kb_uid": kb_uid,
            "file_uid": file_uid,
            "chunk_uid": chunk["chunk_uid"],
            "generation": generation,
            "text": chunk["chunk_text"],
            "embedding": chunk.get("embedding", [0.0]),
        })
    collection.insert(data)
    collection.flush()


def delete_by_file_uid(collection, file_uid: str):
    collection.delete(f'file_uid == "{file_uid}"')
