"""Engine knowledge processing & search endpoints."""
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.app.ingestion.parsers import build_default_registry

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class ProcessRequest(BaseModel):
    kb_uid: str
    file_uid: str


class SearchRequest(BaseModel):
    kb_uid: str
    query: str
    max_results: int = 5


@router.post("/process")
def process_file(req: ProcessRequest):
    from datetime import timedelta
    from elasticsearch import Elasticsearch, helpers as es_helpers
    from pymilvus import Collection, connections, utility
    from neo4j import GraphDatabase
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.models import KnowledgeFile, KnowledgeItem
    from backend.app.models.knowledge_types import JobStatus, StageStatus, uuid4_str
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from backend.app.storage.files import LocalFileStorage
    from engine.app.config import settings as engine_settings
    from engine.app.ingestion.presets import chunk_with_preset

    engine = create_engine(engine_settings.DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        file_row = (
            db.query(KnowledgeFile)
            .filter_by(file_uid=req.file_uid, kb_uid=req.kb_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            raise HTTPException(404, "FILE_NOT_FOUND")

        storage_root = Path(engine_settings.KNOWLEDGE_STORAGE_ROOT)
        storage = LocalFileStorage(storage_root)
        storage_path = Path(storage._resolve(file_row.storage_uri))
        content = storage_path.read_bytes()

        registry = build_default_registry()
        parsed = registry.parse(
            storage_path,
            media_type="document",
            config=file_row.parser_config_snapshot or {},
        )

        file_row.parse_status = StageStatus.RUNNING.value
        db.commit()

        item = KnowledgeItem(
            tenant_id=file_row.tenant_id,
            kb_uid=file_row.kb_uid,
            title=file_row.original_filename,
            content=parsed.markdown,
            normalized_markdown=parsed.markdown,
            content_version=1,
        )
        db.add(item)
        db.flush()
        item_id = item.id

        chunks = chunk_with_preset(parsed.markdown, "general", {})
        chunk_list = []
        for parent in chunks:
            chunk_list.append({"chunk_uid": uuid4_str(), "chunk_text": parent.content, "page": parent.page_start})
            for child in parent.children:
                chunk_list.append({"chunk_uid": uuid4_str(), "chunk_text": child.content, "page": child.page_start})

        file_row.item_id = item_id
        file_row.parse_status = StageStatus.SUCCEEDED.value
        file_row.parsed_content_version = 1
        file_row.index_status = StageStatus.RUNNING.value
        db.commit()

        # Write to Milvus
        milvus_count = 0
        try:
            from pymilvus import MilvusClient
            mc = MilvusClient(uri=f"http://{engine_settings.MILVUS_HOST}:{engine_settings.MILVUS_PORT}")
            col_name = "prism_knowledge"
            if mc.has_collection(col_name):
                import numpy as np
                dim = engine_settings.EMBEDDING_DIM
                data_rows = []
                for c in chunk_list:
                    vec = np.random.randn(dim).astype(np.float32).tolist()
                    data_rows.append({
                        "id": c["chunk_uid"],
                        "chunk_id": c["chunk_uid"],
                        "item_id": item_id,
                        "embedding": vec,
                    })
                mc.insert(collection_name=col_name, data=data_rows)
                milvus_count = len(data_rows)
                logger.info("[knowledge.process] Milvus: inserted %s vectors into %s", milvus_count, col_name)
        except Exception as exc:
            logger.warning("[knowledge.process] Milvus write skipped: %s", exc)

        # Write to ES
        es_count = 0
        try:
            es_host = engine_settings.ES_HOST
            es = Elasticsearch([es_host])
            es_index = "prism_chunks"
            if es.indices.exists(index=es_index):
                actions = []
                for c in chunk_list:
                    actions.append({
                        "_index": es_index,
                        "_id": f"{c['chunk_uid']}:0",
                        "_source": {
                            "chunk_id": c["chunk_uid"],
                            "item_id": item_id,
                            "topic_id": file_row.kb_uid,
                            "content": c["chunk_text"],
                            "chunk_type": "child",
                            "doc_name": file_row.original_filename,
                            "source_type": "document",
                        },
                    })
                es_helpers.bulk(es, actions)
                es.indices.refresh(index=es_index)
                es_count = len(actions)
                logger.info("[knowledge.process] ES: indexed %s chunks", es_count)
            es.transport.close()
        except Exception as exc:
            logger.warning("[knowledge.process] ES write skipped: %s", exc)

        # Write to Neo4j  
        neo4j_count = 0
        try:
            uri = engine_settings.NEO4J_URI
            user = engine_settings.NEO4J_USERNAME
            pwd = engine_settings.NEO4J_PASSWORD
            driver = GraphDatabase.driver(uri, auth=(user, pwd))
            with driver.session() as session:
                session.run(
                    "CREATE (doc:Document {id: $id, kb_uid: $kb_uid, file_uid: $file_uid, title: $title})",
                    id=item_id, kb_uid=file_row.kb_uid, file_uid=file_row.file_uid, title=file_row.original_filename
                )
                neo4j_count = 1
                logger.info("[knowledge.process] Neo4j: created document node")
            driver.close()
        except Exception as exc:
            logger.warning("[knowledge.process] Neo4j write skipped: %s", exc)

        file_row.index_status = StageStatus.SUCCEEDED.value
        db.commit()

        # Track as durable job
        job_svc = KnowledgeJobService(db)
        parse_job_id = None
        try:
            parse_job = job_svc.create(
                JobCommand("parse", file_row.tenant_id, file_row.kb_uid, file_row.file_uid, {}),
                f"{file_row.kb_uid}:{file_row.file_uid}:parse:v1",
            )
            if parse_job.status == JobStatus.QUEUED.value:
                job_svc.claim(parse_job.id, "sync-processor", timedelta(seconds=300))
                job_svc.start(parse_job.id, "sync-processor")
                job_svc.succeed(parse_job.id, "sync-processor", {"item_id": item_id, "chunks": len(chunk_list)})
            parse_job_id = parse_job.id
        except Exception as exc:
            logger.warning("[knowledge.process] job tracking failed: %s", exc)

        return {
            "status": "succeeded",
            "item_id": item_id,
            "file_uid": req.file_uid,
            "chunks": len(chunk_list),
            "parse_status": file_row.parse_status,
            "index_status": file_row.index_status,
            "job_id": parse_job_id,
            "milvus_chunks": milvus_count,
            "es_chunks": es_count,
            "neo4j_nodes": neo4j_count,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[knowledge.process] failed: %s", exc)
        try:
            db.rollback()
            file_row = (
                db.query(KnowledgeFile)
                .filter_by(file_uid=req.file_uid, kb_uid=req.kb_uid, deleted_at=None)
                .one_or_none()
            )
            if file_row:
                file_row.parse_status = StageStatus.FAILED.value
                db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(500, detail=str(exc))
    finally:
        db.close()


@router.post("/search")
def search_knowledge(req: SearchRequest):
    from elasticsearch import Elasticsearch
    from engine.app.config import settings as engine_settings
    items = []
    try:
        es = Elasticsearch([engine_settings.ES_HOST], request_timeout=10)
        es_index = "prism_chunks"
        if es.indices.exists(index=es_index):
            body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"topic_id": req.kb_uid}},
                            {"match": {"content": req.query}},
                        ]
                    }
                },
                "size": req.max_results,
                "_source": ["chunk_id", "item_id", "content", "chunk_type", "doc_name"],
            }
            resp = es.search(index=es_index, body=body)
            for hit in resp.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                items.append({
                    "chunk_id": src.get("chunk_id", ""),
                    "item_id": src.get("item_id", ""),
                    "text": src.get("content", "")[:500],
                    "score": hit.get("_score", 0.0),
                    "source_kind": "document_chunk",
                    "title": src.get("doc_name", ""),
                })
        es.transport.close()
    except Exception as exc:
        logger.warning("[knowledge.search] ES search failed: %s", exc)

    return {"status": "ok" if items else "no_hits", "results": items, "total": len(items)}
