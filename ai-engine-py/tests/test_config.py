"""模型供应商配置测试：LLM / Embedding / Rerank 凭证必须互相独立。"""

from app.core.config import Settings


def test_llm_and_embedding_credentials_are_independent() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://api.deepseek.com",
        llm_api_key="sk-deepseek-only",
        chat_model="deepseek-flash",
        embedding_api_key="",
    )

    assert settings.llm_api_key.get_secret_value() == "sk-deepseek-only"
    assert settings.embedding_api_key.get_secret_value() == ""
    assert settings.chat_model == "deepseek-flash"
    assert settings.embedding_dimensions == 1024
