from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from telethon import errors

from backend.app.main import create_app
from backend.app.telegram.session_manager import AuthFlowError, TelegramSessionManager

API_ID = 123456
API_HASH = "0123456789abcdef0123456789abcdef"
PHONE = "+79990000000"


@dataclass
class FakeUser:
    id: int = 10001
    first_name: str = "Test"
    last_name: str = "User"
    username: str = "test_user"


@dataclass
class FakeTelegramState:
    user: FakeUser | None = None
    require_password: bool = False
    send_code_error: Exception | None = None
    connect_error: Exception | None = None


class FakeTelegramClient:
    def __init__(
        self,
        state: FakeTelegramState,
        session_path: str,
        api_id: int,
        api_hash: str,
    ) -> None:
        self.state = state
        self.session_path = session_path
        self.api_id = api_id
        self.api_hash = api_hash
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        if self.state.connect_error is not None:
            raise self.state.connect_error
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True

    async def get_me(self) -> FakeUser | None:
        return self.state.user

    async def send_code_request(self, phone: str) -> Any:
        if self.state.send_code_error is not None:
            raise self.state.send_code_error
        return SimpleNamespace(phone_code_hash="phone-code-hash")

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | int | None = None,
        *,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ) -> FakeUser:
        if code is not None:
            if str(code) != "12345":
                raise errors.PhoneCodeInvalidError(request=None)
            if self.state.require_password:
                raise errors.SessionPasswordNeededError(request=None)
        if password is not None and password != "correct-password":
            raise errors.PasswordHashInvalidError(request=None)
        self.state.user = FakeUser()
        return self.state.user


class FakeClientFactory:
    def __init__(self, state: FakeTelegramState) -> None:
        self.state = state
        self.clients: list[FakeTelegramClient] = []

    def __call__(
        self, session_path: str, api_id: int, api_hash: str
    ) -> FakeTelegramClient:
        client = FakeTelegramClient(
            self.state, session_path, api_id, api_hash
        )
        self.clients.append(client)
        return client


def build_manager(
    tmp_path: Path,
    state: FakeTelegramState | None = None,
    *,
    challenge_ttl: int = 600,
) -> tuple[TelegramSessionManager, FakeClientFactory]:
    factory = FakeClientFactory(state or FakeTelegramState())
    manager = TelegramSessionManager(
        tmp_path,
        client_factory=factory,
        challenge_ttl=challenge_ttl,
    )
    return manager, factory


@pytest.mark.asyncio
async def test_login_and_restore_saved_session(tmp_path: Path, caplog) -> None:
    state = FakeTelegramState()
    manager, factory = build_manager(tmp_path, state)

    step = await manager.start(API_ID, API_HASH, PHONE)
    assert step.next_step == "code"
    assert factory.clients[0].session_path.endswith("sessions\\account") or factory.clients[
        0
    ].session_path.endswith("sessions/account")

    completed = await manager.verify_code(step.challenge_id, "12345")
    assert completed.next_step == "complete"
    assert completed.account is not None
    assert completed.account.username == "test_user"
    assert API_HASH not in caplog.text
    assert PHONE not in caplog.text

    credentials = (tmp_path / "auth.json").read_text(encoding="utf-8")
    assert API_HASH in credentials

    await manager.close()
    restored_manager = TelegramSessionManager(tmp_path, client_factory=factory)
    await restored_manager.restore()
    restored_account = await restored_manager.status()

    assert restored_account is not None
    assert restored_account.telegram_user_id == 10001
    assert len(factory.clients) == 2
    await restored_manager.close()


@pytest.mark.asyncio
async def test_two_factor_password_flow(tmp_path: Path, caplog) -> None:
    manager, _ = build_manager(
        tmp_path, FakeTelegramState(require_password=True)
    )

    started = await manager.start(API_ID, API_HASH, PHONE)
    password_step = await manager.verify_code(started.challenge_id, "12345")
    assert password_step.next_step == "password"

    with pytest.raises(AuthFlowError, match="Пароль") as error:
        await manager.verify_password(started.challenge_id, "wrong-password")
    assert error.value.code == "password_invalid"

    completed = await manager.verify_password(
        started.challenge_id, "correct-password"
    )
    assert completed.next_step == "complete"
    assert "wrong-password" not in caplog.text
    assert "correct-password" not in caplog.text
    await manager.close()


@pytest.mark.asyncio
async def test_code_error_keeps_challenge_for_retry(tmp_path: Path) -> None:
    manager, _ = build_manager(tmp_path)
    started = await manager.start(API_ID, API_HASH, PHONE)

    with pytest.raises(AuthFlowError) as error:
        await manager.verify_code(started.challenge_id, "00000")
    assert error.value.code == "code_invalid"

    completed = await manager.verify_code(started.challenge_id, "12345")
    assert completed.next_step == "complete"
    await manager.close()


@pytest.mark.asyncio
async def test_flood_wait_and_network_errors(tmp_path: Path) -> None:
    flood_state = FakeTelegramState(
        send_code_error=errors.FloodWaitError(request=None, capture=17)
    )
    flood_manager, flood_factory = build_manager(tmp_path / "flood", flood_state)

    with pytest.raises(AuthFlowError) as flood_error:
        await flood_manager.start(API_ID, API_HASH, PHONE)
    assert flood_error.value.code == "flood_wait"
    assert flood_error.value.retry_after == 17
    assert flood_factory.clients[0].disconnected is True

    network_manager, _ = build_manager(
        tmp_path / "network",
        FakeTelegramState(connect_error=OSError("network down")),
    )
    with pytest.raises(AuthFlowError) as network_error:
        await network_manager.start(API_ID, API_HASH, PHONE)
    assert network_error.value.code == "network_unavailable"


@pytest.mark.asyncio
async def test_expired_challenge_can_be_restarted(tmp_path: Path) -> None:
    manager, _ = build_manager(tmp_path, challenge_ttl=0)
    started = await manager.start(API_ID, API_HASH, PHONE)

    with pytest.raises(AuthFlowError) as error:
        await manager.verify_code(started.challenge_id, "12345")
    assert error.value.code == "challenge_expired"

    restarted = await manager.start(API_ID, API_HASH, PHONE)
    assert restarted.next_step == "code"
    await manager.close()


def test_auth_api_flow_and_secret_safe_validation(tmp_path: Path) -> None:
    manager, _ = build_manager(tmp_path)
    app = create_app(session_manager=manager)

    with TestClient(app) as client:
        initial = client.get("/api/auth/status")
        invalid = client.post(
            "/api/auth/start",
            json={"api_id": API_ID, "api_hash": "secret-value", "phone": PHONE},
        )
        forbidden = client.post(
            "/api/auth/start",
            headers={"Origin": "https://example.com"},
            json={"api_id": API_ID, "api_hash": API_HASH, "phone": PHONE},
        )
        started = client.post(
            "/api/auth/start",
            json={"api_id": API_ID, "api_hash": API_HASH, "phone": PHONE},
        )
        challenge_id = started.json()["challenge_id"]
        invalid_code = client.post(
            "/api/auth/verify-code",
            json={"challenge_id": challenge_id, "code": "00000"},
        )
        completed = client.post(
            "/api/auth/verify-code",
            json={"challenge_id": challenge_id, "code": "12345"},
        )
        status_response = client.get("/api/auth/status")
        logout = client.post("/api/auth/logout")
        logged_out = client.get("/api/auth/status")

    assert initial.json() == {"authenticated": False, "account": None}
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"
    assert "secret-value" not in invalid.text
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "origin_forbidden"
    assert started.status_code == 200
    assert started.json()["next_step"] == "code"
    assert API_HASH not in started.text
    assert PHONE not in started.text
    assert invalid_code.status_code == 400
    assert invalid_code.json()["code"] == "code_invalid"
    assert completed.json()["next_step"] == "complete"
    assert status_response.json()["authenticated"] is True
    assert status_response.json()["account"]["username"] == "test_user"
    assert logout.status_code == 204
    assert logged_out.json() == {"authenticated": False, "account": None}
