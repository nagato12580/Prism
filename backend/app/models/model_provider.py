# prism/backend/app/models/model_provider.py
from sqlalchemy import Boolean, Column, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import uuid4_str


class ModelProvider(Base):
    __tablename__ = "model_provider"
    __table_args__ = (
        UniqueConstraint("provider_id", name="uq_model_provider_provider_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    provider_id = Column(String(64), nullable=False)
    display_name = Column(String(255), nullable=False)
    provider_type = Column(String(32), nullable=False, default="openai")
    base_url = Column(String(1024), nullable=False)
    models_endpoint = Column(String(1024), nullable=True)
    api_key_env = Column(String(64), nullable=True)
    api_key = Column(Text, nullable=True, comment="Fernet-encrypted inline key; api_key_env takes precedence")
    capabilities = Column(JSON, nullable=True)
    enabled_models = Column(JSON, nullable=True)
    headers_json = Column(JSON, nullable=True)
    extra_json = Column(JSON, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    is_builtin = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
