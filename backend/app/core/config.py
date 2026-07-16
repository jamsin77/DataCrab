"""应用配置模块"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "DataCrab"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./datacrab.db"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None

    # JWT配置
    JWT_SECRET_KEY: str = "datacrab-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7天

    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # MinIO配置
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "datacrab"
    MINIO_SECURE: bool = False

    # Elasticsearch配置
    ELASTICSEARCH_URL: str = "http://localhost:9200"

    # LLM配置
    LLM_PROVIDER: str = "glm"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None
    OPENAI_MODEL: str = "glm-5.2"
    # 快速模型（用于调试对话等不需要深度推理的场景，为空时自动按 provider 选择）
    LLM_FAST_MODEL: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-ada-002"
    # 降级模型链：JSON 数组，如 [{"provider":"qwen","api_key":"...","model":"qwen-plus"}, {...}]
    LLM_FALLBACK_MODELS: str = ""

    # 加密密钥（用于 API Key 等敏感信息加密存储）
    ENCRYPT_KEY: str = ""

    # CORS配置
    CORS_ORIGINS: list = ["http://localhost:5173", "http://localhost:3000"]

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = None

    # Skill存储配置
    SKILL_STORAGE_PATH: str = "data/skills"
    SKILL_RUNNER_TIMEOUT: int = 300

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()

import os as _os
if not _os.path.isabs(settings.SKILL_STORAGE_PATH):
    _backend_dir = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    settings.SKILL_STORAGE_PATH = _os.path.join(_backend_dir, settings.SKILL_STORAGE_PATH)
