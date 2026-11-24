from __future__ import annotations

from pathlib import Path

import pytest

import launcher


class ReadyResponse:
    status = 200

    def __enter__(self) -> ReadyResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeProcess:
    def __init__(self, *, interrupt: bool = False) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.interrupt = interrupt
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: int | None = None) -> int:
        self.wait_calls += 1
        if self.interrupt and self.wait_calls == 1 and timeout is None:
            raise KeyboardInterrupt
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


def prepare_frontend(path: Path) -> None:
    dist = path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<main>ready</main>", encoding="utf-8")


def test_launcher_opens_browser_after_backend_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_frontend(tmp_path)
    process = FakeProcess()
    opened: list[str] = []
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *args, **kwargs: ReadyResponse())
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(launcher.sys, "argv", ["launcher.py"])
    monkeypatch.delenv("TELEGRAM_MANAGER_HOST", raising=False)
    monkeypatch.delenv("TELEGRAM_MANAGER_PORT", raising=False)

    assert launcher.main() == 0
    assert opened == ["http://127.0.0.1:8000"]


def test_launcher_stops_backend_tree_on_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_frontend(tmp_path)
    process = FakeProcess(interrupt=True)
    commands: list[list[str]] = []
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *args, **kwargs: ReadyResponse())
    monkeypatch.setattr(launcher.sys, "argv", ["launcher.py", "--no-browser"])
    monkeypatch.delenv("TELEGRAM_MANAGER_HOST", raising=False)
    monkeypatch.delenv("TELEGRAM_MANAGER_PORT", raising=False)

    assert launcher.main() == 0
    assert commands == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_launcher_rejects_public_bind_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_MANAGER_HOST", "0.0.0.0")
    assert launcher.main() == 1
