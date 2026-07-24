# prism/engine/app/config.py
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


def _env(name: str, default: str = "", *fallback_names: str) -> str:
    for key in (name, *fallback_names):
        value = os.getenv(key)
        if value:
            return value
    return default


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    KNOWLEDGE_INGEST_QUEUE: str = os.getenv(
        "KNOWLEDGE_INGEST_QUEUE", "prism:queue:ingest"
    )
    KNOWLEDGE_GOVERNANCE_QUEUE: str = os.getenv(
        "KNOWLEDGE_GOVERNANCE_QUEUE", "prism:queue:governance"
    )
    KNOWLEDGE_INGEST_WORKERS: int = int(os.getenv("KNOWLEDGE_INGEST_WORKERS", "2"))
    KNOWLEDGE_GOVERNANCE_WORKERS: int = int(
        os.getenv("KNOWLEDGE_GOVERNANCE_WORKERS", "1")
    )
    KNOWLEDGE_JOB_STALE_SECONDS: int = int(
        os.getenv("KNOWLEDGE_JOB_STALE_SECONDS", "1800")
    )
    KNOWLEDGE_TEXT_MAX_CHARS: int = int(
        os.getenv("KNOWLEDGE_TEXT_MAX_CHARS", "300000")
    )
    KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE: int = int(
        os.getenv("KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE", "12000")
    )
    MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT: int = int(os.getenv("MILVUS_PORT", "19530"))
    MILVUS_OPERATION_TIMEOUT_SECONDS: float = float(os.getenv("MILVUS_OPERATION_TIMEOUT_SECONDS", "5"))
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")
    ENTITY_GRAPH_ENABLED: bool = os.getenv("ENTITY_GRAPH_ENABLED", "0") == "1"

    ENGINE_HOST: str = os.getenv("ENGINE_HOST", "0.0.0.0")
    ENGINE_PORT: int = int(os.getenv("ENGINE_PORT", "5180"))

    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-plus")
    ENTITY_EXTRACT_MODEL: str = os.getenv("ENTITY_EXTRACT_MODEL", "")
    ENTITY_EXTRACT_WORKERS: int = int(os.getenv("ENTITY_EXTRACT_WORKERS", "4"))
    ENTITY_EXTRACT_TIMEOUT_SECONDS: float = float(os.getenv("ENTITY_EXTRACT_TIMEOUT_SECONDS", "30"))
    ENTITY_EXTRACT_ENABLED: bool = os.getenv("ENTITY_EXTRACT_ENABLED", "1") not in ("0", "false", "False")
    GRAPH_ANALYSIS_ENABLED: bool = os.getenv("GRAPH_ANALYSIS_ENABLED", "1") not in ("0", "false", "False")

    # ---- P5 graph insights injection ----
    GRAPH_INSIGHTS_ENABLED: bool = os.getenv("GRAPH_INSIGHTS_ENABLED", "1") not in ("0", "false", "False")
    GRAPH_INSIGHTS_TIMEOUT_SECONDS: float = float(os.getenv("GRAPH_INSIGHTS_TIMEOUT_SECONDS", "3.0"))
    GRAPH_INSIGHTS_SEED_ENTITIES: int = int(os.getenv("GRAPH_INSIGHTS_SEED_ENTITIES", "6"))
    GRAPH_INSIGHTS_MAX_SURPRISING: int = int(os.getenv("GRAPH_INSIGHTS_MAX_SURPRISING", "2"))
    GRAPH_INSIGHTS_MAX_GOD: int = int(os.getenv("GRAPH_INSIGHTS_MAX_GOD", "2"))
    GRAPH_INSIGHTS_MAX_QUESTIONS: int = int(os.getenv("GRAPH_INSIGHTS_MAX_QUESTIONS", "2"))
    COMMUNITY_LABEL_MODEL: str = os.getenv("COMMUNITY_LABEL_MODEL", "")

    # ---- P4 graph-driven CKP governance ----
    GRAPH_GOV_ENABLED: bool = os.getenv("GRAPH_GOV_ENABLED", "1") not in ("0", "false", "False")
    GRAPH_GOV_COHESION_THRESHOLD: float = float(os.getenv("GRAPH_GOV_COHESION_THRESHOLD", "0.3"))

    # ---- P3 unified GraphRAG retrieval ----
    RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "1") not in ("0", "false", "False")
    RERANK_API_BASE: str = os.getenv("RERANK_API_BASE", "")
    RERANK_API_KEY: str = os.getenv("RERANK_API_KEY", "")
    RERANK_MODEL: str = os.getenv("RERANK_MODEL", "")
    RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "20"))
    RERANK_TIMEOUT_SECONDS: float = float(os.getenv("RERANK_TIMEOUT_SECONDS", "10"))
    GRAPH_EXPAND_FAST_HOPS: int = int(os.getenv("GRAPH_EXPAND_FAST_HOPS", "1"))
    GRAPH_EXPAND_DEEP_HOPS: int = int(os.getenv("GRAPH_EXPAND_DEEP_HOPS", "2"))
    GRAPH_EXPAND_SEED_ENTITIES: int = int(os.getenv("GRAPH_EXPAND_SEED_ENTITIES", "10"))
    GRAPH_EXPAND_NEIGHBORS_PER_NODE: int = int(os.getenv("GRAPH_EXPAND_NEIGHBORS_PER_NODE", "8"))
    GRAPH_EXPAND_COMMUNITY_MEMBERS: int = int(os.getenv("GRAPH_EXPAND_COMMUNITY_MEMBERS", "10"))
    GRAPH_EXPAND_GOD_NEIGHBORS: int = int(os.getenv("GRAPH_EXPAND_GOD_NEIGHBORS", "10"))
    GRAPH_EXPAND_MAX_CANDIDATES: int = int(os.getenv("GRAPH_EXPAND_MAX_CANDIDATES", "60"))

    AGENT_TOOL_TIMEOUT_SECONDS: float = float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "12"))
    KNOWLEDGE_SCOPE_SECRET: str = os.getenv("KNOWLEDGE_SCOPE_SECRET", "")
    DEEP_SEARCH_JUDGE_API_BASE: str = os.getenv("DEEP_SEARCH_JUDGE_API_BASE", "")
    DEEP_SEARCH_JUDGE_API_KEY: str = os.getenv("DEEP_SEARCH_JUDGE_API_KEY", "")
    DEEP_SEARCH_JUDGE_MODEL: str = os.getenv("DEEP_SEARCH_JUDGE_MODEL", "")
    DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE: float = float(os.getenv("DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", "0.72"))
    DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE: int = int(os.getenv("DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", "1"))

    EMBEDDING_API_BASE: str = _env("EMBEDDING_API_BASE", "https://api.siliconflow.cn/v1")
    EMBEDDING_API_KEY: str = _env("EMBEDDING_API_KEY", "", "SILICONFLOW_API_KEY")
    EMBEDDING_MODEL: str = _env("EMBEDDING_MODEL", "BAAI/bge-m3")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1024"))
    EMBEDDING_TIMEOUT_SECONDS: float = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60"))
    EMBEDDING_MAX_RETRIES: int = int(os.getenv("EMBEDDING_MAX_RETRIES", "2"))
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
    CHILD_CHUNK_TOKENS: int = int(os.getenv("CHILD_CHUNK_TOKENS", "384"))
    PARENT_CHUNK_TOKENS: int = int(os.getenv("PARENT_CHUNK_TOKENS", "1536"))
    CHILD_OVERLAP_RATIO: float = float(os.getenv("CHILD_OVERLAP_RATIO", "0.1"))

    KNOWLEDGE_STORAGE_ROOT: str = os.getenv("KNOWLEDGE_STORAGE_ROOT", str(Path(__file__).resolve().parent.parent.parent / "uploads_data"))
    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_USERNAME: str = os.getenv("ES_USERNAME", "")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "")


settings = Settings()
