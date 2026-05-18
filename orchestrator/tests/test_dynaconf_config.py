from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import get_config, load_config


def _write_config(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _clear_config_cache() -> None:
    get_config.cache_clear()


def test_config_env_override_and_type_casting(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_config_cache()
    monkeypatch.setenv("ORCHESTRATOR_DEBUG", "true")
    monkeypatch.setenv("ORCHESTRATOR_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ORCHESTRATOR_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv(
        "ORCHESTRATOR_MCP__GITHUB__HEADERS__Authorization",
        "Bearer test",
    )

    config = get_config()

    assert config.debug is True
    assert config.log_level == "WARNING"
    assert config.openai_api_key == "sk-test"


def test_load_config_supports_nested_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        """
database:
  pool_size: 3
  max_overflow: 5
""".strip(),
    )

    monkeypatch.setenv("ORCHESTRATOR_DATABASE__POOL_SIZE", "7")
    monkeypatch.setenv(
        "ORCHESTRATOR_DATABASE__MAX_OVERFLOW",
        "9",
    )

    config = load_config(config_path)

    assert config.database.pool_size == 7
    assert config.database.max_overflow == 9


def test_load_config_rejects_invalid_database_pool_size(tmp_path: Path) -> None:
    from pydantic import ValidationError

    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        """
database:
  pool_size: not-an-int
""".strip(),
    )

    with pytest.raises(ValidationError):
        load_config(config_path)
