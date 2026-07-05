# prism/backend/app/config.py
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings:
    APP_TIMEZONE: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    DATABASE_TIME_ZONE: str = os.getenv("DATABASE_TIME_ZONE", "+08:00")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    KNOWLEDGE_INGEST_QUEUE: str = os.getenv("KNOWLEDGE_INGEST_QUEUE", "prism:queue:ingest")
    KNOWLEDGE_GOVERNANCE_QUEUE: str = os.getenv("KNOWLEDGE_GOVERNANCE_QUEUE", "prism:queue:governance")
    KNOWLEDGE_TEXT_MAX_CHARS: int = int(os.getenv("KNOWLEDGE_TEXT_MAX_CHARS", "300000"))
    KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE: int = int(os.getenv("KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE", "12000"))
    MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT: int = int(os.getenv("MILVUS_PORT", "19530"))
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")
    ENTITY_GRAPH_ENABLED: bool = os.getenv("ENTITY_GRAPH_ENABLED", "1") == "1"

    KMC_HOST: str = os.getenv("KMC_HOST", "0.0.0.0")
    KMC_PORT: int = int(os.getenv("KMC_PORT", "5175"))
    ENGINE_HOST: str = os.getenv("ENGINE_HOST", "0.0.0.0")
    ENGINE_PORT: int = int(os.getenv("ENGINE_PORT", "5180"))
    ENGINE_BASE_URL: str = os.getenv("ENGINE_BASE_URL", f"http://127.0.0.1:{ENGINE_PORT}")

    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen-plus")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    PKU_TYPE_MODEL: str = os.getenv("OLLAMA_BASE_MODEL", "qwen2.5:3b")
    PKU_TYPE_TIMEOUT: float = float(os.getenv("PKU_TYPE_TIMEOUT", "8"))
    PKU_TYPE_USE_OLLAMA: bool = os.getenv("PKU_TYPE_USE_OLLAMA", "1") != "0"

    EMBEDDING_API_BASE: str = os.getenv("EMBEDDING_API_BASE", "")
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "bge-m3")
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1024"))

    ASR_PROVIDER: str = os.getenv("ASR_PROVIDER", "dashscope")
    ASR_API_KEY: str = os.getenv("ASR_API_KEY", "")
    ASR_MODEL: str = os.getenv("ASR_MODEL", "paraformer-v2")
    WHISPER_SERVICE_URL: str = os.getenv("WHISPER_SERVICE_URL", "http://localhost:5199")

    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_USERNAME: str = os.getenv("ES_USERNAME", "")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "")

    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret")
    MEMORY_EXTRACTION_AUTO_ENABLED: bool = os.getenv("MEMORY_EXTRACTION_AUTO_ENABLED", "0") == "1"
    MEMORY_SCHEDULED_ENABLED: bool = os.getenv("MEMORY_SCHEDULED_ENABLED", "1") == "1"
    MEMORY_SCHEDULED_INTERVAL_MINUTES: int = int(os.getenv("MEMORY_SCHEDULED_INTERVAL_MINUTES", "30"))
    MEMORY_SCHEDULED_MAX_SESSIONS: int = int(os.getenv("MEMORY_SCHEDULED_MAX_SESSIONS", "10"))
    MEMORY_SCHEDULED_CONTEXT_WINDOW: int = int(os.getenv("MEMORY_SCHEDULED_CONTEXT_WINDOW", "5"))
    MEMORY_AUTO_CONFIRM_THRESHOLD: float = float(os.getenv("MEMORY_AUTO_CONFIRM_THRESHOLD", "0.85"))


settings = Settings()
