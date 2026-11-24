"""应用配置：全部来自环境变量 / .env，启动时完成类型与安全校验。"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_INTERNAL_TOKEN = "dev-internal-token-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 运行环境
    app_env: Literal["development", "staging", "production"] = "development"
    app_version: str = "0.1.0"
    api_prefix: str = "/internal/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # 内部鉴权：网关调用时必须携带 X-Internal-Token
    internal_token: SecretStr = SecretStr(DEFAULT_INTERNAL_TOKEN)

    # PostgreSQL + pgvector
    database_url: str = "postgresql+asyncpg://workspace:workspace@127.0.0.1:5432/workspace"
    db_pool_size: int = Field(default=10, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    db_echo: bool = False

    # 大模型与检索模型（Phase 2 使用）
    # 对话/Agent/改写可使用 DeepSeek、DashScope 或任意 OpenAI 兼容端点；
    # Embedding/Rerank 必须使用各自独立的供应商（DeepSeek 当前不提供这两个 API）。
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: SecretStr = SecretStr("")
    chat_model: str = "qwen-plus"
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)

    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = "text-embedding-v3"
    embedding_dimensions: int = Field(default=1024, ge=1024, le=1024)

    rerank_base_url: str = ""
    rerank_api_key: SecretStr = SecretStr("")
    rerank_model: str = "bge-reranker-v2-m3"

    # 阿里云 OSS（Phase 2 文档下载）
    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: SecretStr = SecretStr("")
    oss_access_key_secret: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_production_safety(self) -> Self:
        if self.app_env == "production":
            token = self.internal_token.get_secret_value()
            if token == DEFAULT_INTERNAL_TOKEN or len(token) < 32:
                raise ValueError("生产环境 INTERNAL_TOKEN 必须替换默认值且长度不小于 32")
            if not self.llm_api_key.get_secret_value():
                raise ValueError("生产环境必须配置 LLM_API_KEY")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例，便于 FastAPI Depends 与测试覆写。"""
    return Settings()
