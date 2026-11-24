from __future__ import annotations

import pytest

from backend.app.core.config import load_settings


def test_settings_accept_only_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_MANAGER_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        load_settings()

    monkeypatch.setenv("TELEGRAM_MANAGER_HOST", "127.0.0.1")
    monkeypatch.setenv("TELEGRAM_MANAGER_PORT", "65536")
    with pytest.raises(ValueError, match="65535"):
        load_settings()


def test_settings_reject_nonlocal_cors_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_MANAGER_HOST", "localhost")
    monkeypatch.setenv("TELEGRAM_MANAGER_PORT", "8000")
    monkeypatch.setenv("TELEGRAM_MANAGER_CORS_ORIGINS", "https://example.com")

    with pytest.raises(ValueError, match="loopback"):
        load_settings()


def test_release_settings_are_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_MANAGER_HOST", "::1")
    monkeypatch.setenv(
        "TELEGRAM_MANAGER_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    settings = load_settings()

    assert settings.host == "::1"
    assert settings.version == "0.1.0"
