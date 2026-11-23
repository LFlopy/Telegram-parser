"""Локальный запуск Telegram Manager.

Использование:
    python launcher.py          # старт, дождаться готовности, открыть браузер
    python launcher.py --no-browser   # без автооткрытия браузера
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _settings_from_env() -> tuple[str, int]:
    host = os.environ.get("TELEGRAM_MANAGER_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("TELEGRAM_MANAGER_PORT", "8000"))
    except ValueError:
        port = 8000
    return host, port


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Не удалось завершить процесс backend принудительно.")


def main() -> int:
    _load_dotenv()
    host, port = _settings_from_env()
    base_url = f"http://{host}:{port}"
    open_browser = "--no-browser" not in sys.argv

    index_file = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    if not index_file.is_file():
        print("Панель не собрана. Выполните: npm --prefix frontend run build")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    print(f"Запуск backend: {' '.join(cmd)}")
    popen_kwargs: dict = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, **popen_kwargs)

    deadline = time.monotonic() + 30
    ready = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print("Backend аварийно завершился до старта:", proc.returncode)
            return 1
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except (OSError, TimeoutError):
            time.sleep(0.4)

    if not ready:
        print(f"Backend не ответил на /api/health за 30 секунд (ожидался {base_url}).")
        _terminate(proc)
        return 1

    if ready:
        print(f"Backend готов: {base_url}")
        if open_browser:
            print("Открываю браузер...")
            webbrowser.open(base_url)

    print("Остановите приложение по Ctrl+C.")
    try:
        proc.wait()
        return proc.returncode if proc.returncode is not None else 0
    except KeyboardInterrupt:
        print("\nОстанавливаю...")
        _terminate(proc)
        return 0
    except OSError as exc:
        print(f"Ошибка процесса backend: {exc}")
        _terminate(proc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
