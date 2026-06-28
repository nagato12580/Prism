# prism/engine/app/milvus_client.py
"""Milvus 向量库客户端封装。"""
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
from .config import settings

COLLECTION_NAME = "prism_knowledge"


def connect():
    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)


def ensure_collection():
    """确保集合存在，不存在则创建。"""
    connect()
    if utility.has_collection(COLLECTION_NAME):
        return Collection(COLLECTION_NAME)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM),
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="item_id", dtype=DataType.VARCHAR, max_length=64),
    ]
    schema = CollectionSchema(fields, description="Prism 知识块向量")
    collection = Collection(COLLECTION_NAME, schema)

    # 创建索引
    collection.create_index(
        field_name="embedding",
        index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE",
                      "params": {"nlist": 128}},
    )
    return collection


def insert_vectors(chunk_id: str, item_id: str, embedding: list[float]):
    """插入一条向量。"""
    insert_vectors_batch([
        {"chunk_id": chunk_id, "item_id": item_id, "embedding": embedding},
    ])


def insert_vectors_batch(rows: list[dict]):
    """Batch insert vectors."""
    if not rows:
        return

    coll = ensure_collection()
    chunk_ids = [row["chunk_id"] for row in rows]
    embeddings = [row["embedding"] for row in rows]
    item_ids = [row["item_id"] for row in rows]

    coll.insert([
        chunk_ids,      # id (VARCHAR)
        embeddings,     # embedding (FLOAT_VECTOR)
        chunk_ids,      # chunk_id (VARCHAR)
        item_ids,       # item_id (VARCHAR)
    ])


def delete_vectors_by_item(item_id: str):
    """Delete all vectors for one knowledge item."""
    if not item_id:
        return

    coll = ensure_collection()
    escaped_item_id = item_id.replace("\\", "\\\\").replace('"', '\\"')
    coll.delete(expr=f'item_id == "{escaped_item_id}"')
    coll.flush()


def search_vectors(query_embedding: list[float], top_k: int = 10) -> list[dict]:
    """向量检索，返回 [{chunk_id, item_id, score}]。

    集合常驻内存（load 在已加载时是空操作），不再每次 release。
    """
    coll = ensure_collection()
    coll.load()  # 已加载时为 no-op
    results = coll.search(
        data=[query_embedding],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 32}},
        limit=top_k,
        output_fields=["chunk_id", "item_id"],
    )
    hits = []
    for hit in results[0]:
        hits.append({
            "chunk_id": hit.entity.get("chunk_id"),
            "item_id": hit.entity.get("item_id"),
            "score": hit.score,
        })
    return hits
