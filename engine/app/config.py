# prism/engine/app/config.py
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


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

    ENGINE_HOST: str = os.getenv("ENGINE_HOST", "0.0.0.0")
    ENGINE_PORT: int = int(os.getenv("ENGINE_PORT", "5180"))

    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-plus")
    DEEP_SEARCH_JUDGE_API_BASE: str = os.getenv("DEEP_SEARCH_JUDGE_API_BASE", "")
    DEEP_SEARCH_JUDGE_API_KEY: str = os.getenv("DEEP_SEARCH_JUDGE_API_KEY", "")
    DEEP_SEARCH_JUDGE_MODEL: str = os.getenv("DEEP_SEARCH_JUDGE_MODEL", "")
    DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE: float = float(os.getenv("DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", "0.72"))
    DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE: int = int(os.getenv("DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", "1"))

    EMBEDDING_API_BASE: str = os.getenv("EMBEDDING_API_BASE", "")
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "bge-m3")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1024"))
    EMBEDDING_TIMEOUT_SECONDS: float = float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60"))
    EMBEDDING_MAX_RETRIES: int = int(os.getenv("EMBEDDING_MAX_RETRIES", "2"))
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
    CHILD_CHUNK_TOKENS: int = int(os.getenv("CHILD_CHUNK_TOKENS", "384"))
    PARENT_CHUNK_TOKENS: int = int(os.getenv("PARENT_CHUNK_TOKENS", "1536"))
    CHILD_OVERLAP_RATIO: float = float(os.getenv("CHILD_OVERLAP_RATIO", "0.1"))

    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_USERNAME: str = os.getenv("ES_USERNAME", "")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "")


settings = Settings()
