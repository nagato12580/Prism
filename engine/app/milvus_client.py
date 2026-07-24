# prism/engine/app/milvus_client.py
"""Milvus 向量库客户端封装 — 使用 MilvusClient API（PyMilvus 3.x）。"""
from pymilvus import MilvusClient, DataType, CollectionSchema, FieldSchema
from pymilvus.exceptions import MilvusException

from .config import settings

COLLECTION_NAME = "prism_knowledge"
MILVUS_OPERATION_TIMEOUT_SECONDS = settings.MILVUS_OPERATION_TIMEOUT_SECONDS

_client: MilvusClient | None = None


def _build_schema() -> CollectionSchema:
    """Build a CollectionSchema for the prism knowledge collection."""
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="item_id", dtype=DataType.VARCHAR, max_length=64),
    ]
    return CollectionSchema(fields=fields)

_INDEX_PARAMS = {
    "field_name": "embedding",
    "index_type": "IVF_FLAT",
    "metric_type": "COSINE",
    "params": {"nlist": 128},
}


def _get_client() -> MilvusClient:
    """获取 MilvusClient 单例。"""
    global _client
    if _client is None:
        _client = MilvusClient(
            uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}",
        )
    return _client


def connect() -> MilvusClient:
    """Initialize and return the shared Milvus client."""
    return _get_client()


def ensure_collection():
    """确保集合存在，并保证向量字段上有可用索引。

    pymilvus 2.4 的 ``create_collection(index_params=<dict>)`` 不会真正建索引
    （会触发 ``'str' object has no attribute 'pop'``），因此先建集合，再单独、
    幂等地为 ``embedding`` 字段创建 IVF_FLAT/COSINE 索引。
    """
    client = _get_client()
    if not client.has_collection(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=_build_schema(),
        )
    _ensure_vector_index(client)


def _ensure_vector_index(client: MilvusClient) -> None:
    try:
        indexes = client.list_indexes(collection_name=COLLECTION_NAME)
    except Exception:
        indexes = []
    if indexes:
        return
    # pymilvus 2.4: create_index requires a prepared IndexParams object, not a dict.
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=_INDEX_PARAMS["field_name"],
        index_type=_INDEX_PARAMS["index_type"],
        metric_type=_INDEX_PARAMS["metric_type"],
        params=_INDEX_PARAMS["params"],
    )
    client.create_index(collection_name=COLLECTION_NAME, index_params=index_params)


def _load_collection():
    ensure_collection()
    _get_client().load_collection(
        collection_name=COLLECTION_NAME,
        timeout=MILVUS_OPERATION_TIMEOUT_SECONDS,
    )


def insert_vectors(chunk_id: str, item_id: str, embedding: list[float]):
    """插入一条向量。"""
    insert_vectors_batch([
        {"chunk_id": chunk_id, "item_id": item_id, "embedding": embedding},
    ])


def insert_vectors_batch(rows: list[dict]):
    """Batch insert vectors."""
    if not rows:
        return

    client = _get_client()
    ensure_collection()

    data = []
    for row in rows:
        data.append({
            "id": row["chunk_id"],
            "chunk_id": row["chunk_id"],
            "item_id": row["item_id"],
            "embedding": row["embedding"],
        })

    client.insert(collection_name=COLLECTION_NAME, data=data)


def delete_vectors_by_item(item_id: str):
    """Delete all vectors for one knowledge item."""
    if not item_id:
        return

    client = _get_client()
    if not client.has_collection(COLLECTION_NAME):
        return
    escaped_item_id = item_id.replace("\\", "\\\\").replace('"', '\\"')
    try:
        client.load_collection(
            collection_name=COLLECTION_NAME,
            timeout=MILVUS_OPERATION_TIMEOUT_SECONDS,
        )
        client.delete(
            collection_name=COLLECTION_NAME,
            filter=f'item_id == "{escaped_item_id}"',
            timeout=MILVUS_OPERATION_TIMEOUT_SECONDS,
        )
    except MilvusException as exc:
        message = str(exc)
        if "index not found" in message or "collection not loaded" in message:
            return
        raise


def delete_vectors_by_ids(chunk_ids: list[str]):
    """Delete vectors by their Milvus primary keys."""
    ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
    if not ids:
        return

    client = _get_client()
    ensure_collection()
    client.delete(
        collection_name=COLLECTION_NAME,
        ids=ids,
        timeout=MILVUS_OPERATION_TIMEOUT_SECONDS,
    )


def search_vectors(query_embedding: list[float], top_k: int = 10) -> list[dict]:
    """向量检索，返回 [{chunk_id, item_id, score}]。"""
    client = _get_client()
    _load_collection()

    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_embedding],
        anns_field="embedding",
        search_params={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=top_k,
        output_fields=["chunk_id", "item_id"],
        timeout=MILVUS_OPERATION_TIMEOUT_SECONDS,
    )

    hits = []
    for hit in results[0]:
        entity = hit.get("entity", hit)
        hits.append({
            "chunk_id": entity.get("chunk_id"),
            "item_id": entity.get("item_id"),
            "score": hit.get("distance", hit.get("score", 0)),
        })
    return hits
