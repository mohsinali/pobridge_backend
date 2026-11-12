"""Settings behavior tests."""

from app.core.config import Settings


def test_api_key_is_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    settings = Settings(_env_file=None)
    assert settings.OPENAI_API_KEY == "test-key"
    assert settings.OPENAI_MODEL == "test-model"


def test_api_key_may_be_missing_at_startup(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.OPENAI_API_KEY is None
