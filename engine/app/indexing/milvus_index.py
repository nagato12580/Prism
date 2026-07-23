# engine/app/indexing/milvus_index.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from pymilvus import Collection, connections, utility

from engine.app.indexing.profiles import EmbeddingProfile, DEFAULT_PROFILE


def _connect(host: str = "127.0.0.1", port: int = 19530):
    try:
        if not connections.has_connection("default"):
            connections.connect("default", host=host, port=port)
    except Exception:
        raise RuntimeError("MILVUS_UNAVAILABLE")


def ensure_collection(profile: EmbeddingProfile | None = None):
    profile = profile or DEFAULT_PROFILE
    _connect()
    if utility.has_collection(profile.collection_name):
        return Collection(profile.collection_name)
    from pymilvus import CollectionSchema, DataType, FieldSchema
    fields = [
        FieldSchema("id", DataType.VARCHAR, max_length=100, is_primary=True),
        FieldSchema("kb_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("file_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("chunk_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("generation", DataType.VARCHAR, max_length=36),
        FieldSchema("text", DataType.VARCHAR, max_length=65535),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=profile.dimension),
    ]
    schema = CollectionSchema(fields, description="Prism knowledge chunks")
    collection = Collection(profile.collection_name, schema)
    index_params = {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index("embedding", index_params)
    collection.load()
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
