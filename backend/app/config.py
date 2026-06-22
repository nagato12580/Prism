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
    MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT: int = int(os.getenv("MILVUS_PORT", "19530"))

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

    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_USERNAME: str = os.getenv("ES_USERNAME", "")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "")

    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret")


settings = Settings()
