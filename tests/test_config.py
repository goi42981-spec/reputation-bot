"""Tests for environment-driven config parsing."""

from __future__ import annotations

import pytest

from reputation_bot.config import Config


def test_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)
    monkeypatch.delenv("ALLOWED_CHAT_IDS", raising=False)

    cfg = Config.from_env()
    assert cfg.bot_token == "123:abc"
    assert cfg.database_url == "reputation.db"
    assert cfg.super_owner_id is None
    assert cfg.allowed_chat_ids == frozenset()


def test_from_env_requires_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        Config.from_env()


def test_allowed_chat_ids_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "-1001234567890, -1009876543210")
    cfg = Config.from_env()
    assert cfg.allowed_chat_ids == frozenset({-1001234567890, -1009876543210})


def test_allowed_chat_ids_whitespace_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "111 222\t333")
    cfg = Config.from_env()
    assert cfg.allowed_chat_ids == frozenset({111, 222, 333})


def test_allowed_chat_ids_empty_means_no_restriction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "   ")
    cfg = Config.from_env()
    assert cfg.allowed_chat_ids == frozenset()


def test_allowed_chat_ids_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "111,notanumber")
    with pytest.raises(RuntimeError, match="ALLOWED_CHAT_IDS"):
        Config.from_env()


def test_owner_id_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("OWNER_ID", "42")
    cfg = Config.from_env()
    assert cfg.super_owner_id == 42


def test_owner_id_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("OWNER_ID", "abc")
    with pytest.raises(RuntimeError, match="OWNER_ID"):
        Config.from_env()
