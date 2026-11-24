from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol, cast
from uuid import uuid4

from telethon import TelegramClient, errors

logger = logging.getLogger("telegram_manager.auth")

TELETHON_EXCEPTIONS = (
    errors.RPCError,
    OSError,
    TimeoutError,
    ConnectionError,
    ValueError,
)


class TelegramClientProtocol(Protocol):
    async def connect(self) -> Any: ...

    def disconnect(self) -> Awaitable[Any] | None: ...

    async def get_me(self) -> Any: ...

    async def send_code_request(self, phone: str) -> Any: ...

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | int | None = None,
        *,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ) -> Any: ...


ClientFactory = Callable[[str, int, str], TelegramClientProtocol]


@dataclass(frozen=True)
class AccountInfo:
    telegram_user_id: int
    display_name: str
    username: str | None


@dataclass(frozen=True)
class AuthStep:
    challenge_id: str
    next_step: Literal["code", "password", "complete"]
    account: AccountInfo | None = None


@dataclass
class AuthChallenge:
    challenge_id: str
    client: TelegramClientProtocol
    api_id: int
    api_hash: str
    phone: str
    phone_code_hash: str
    expires_at: float


class AuthFlowError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


def _default_client_factory(
    session_path: str, api_id: int, api_hash: str
) -> TelegramClientProtocol:
    return cast(
        TelegramClientProtocol,
        TelegramClient(
            session_path,
            api_id,
            api_hash,
            flood_sleep_threshold=0,
        ),
    )


class TelegramSessionManager:
    def __init__(
        self,
        data_dir: Path,
        *,
        client_factory: ClientFactory = _default_client_factory,
        challenge_ttl: int = 600,
    ) -> None:
        self._data_dir = data_dir
        self._sessions_dir = data_dir / "sessions"
        self._session_path = self._sessions_dir / "account"
        self._credentials_path = data_dir / "auth.json"
        self._client_factory = client_factory
        self._challenge_ttl = challenge_ttl
        self._client: TelegramClientProtocol | None = None
        self._account: AccountInfo | None = None
        self._challenge: AuthChallenge | None = None
        self._lock = asyncio.Lock()

    async def restore(self) -> None:
        async with self._lock:
            if self._client is not None or not self._credentials_path.is_file():
                return
            credentials = self._read_credentials()
            if credentials is None:
                return
            client = self._client_factory(
                str(self._session_path),
                credentials["api_id"],
                credentials["api_hash"],
            )
            try:
                await client.connect()
                self._secure_session_files()
                user = await client.get_me()
                if user is None:
                    await self._disconnect_safely(client)
                    logger.warning("Saved Telegram session is no longer authorized")
                    return
                self._client = client
                self._account = self._account_from_user(user)
                logger.info("Telegram session restored")
            except TELETHON_EXCEPTIONS as exc:
                await self._disconnect_safely(client)
                logger.warning(
                    "Cannot restore Telegram session (%s)",
                    type(exc).__name__,
                )

    async def status(self) -> AccountInfo | None:
        async with self._lock:
            return self._account

    async def require_client(self) -> TelegramClientProtocol:
        async with self._lock:
            if self._client is None or self._account is None:
                raise AuthFlowError(
                    "not_authenticated",
                    "Сначала подключите Telegram-аккаунт.",
                    401,
                )
            return self._client

    async def start(
        self, api_id: int, api_hash: str, phone: str
    ) -> AuthStep:
        async with self._lock:
            await self._expire_challenge(raise_error=False)
            if self._client is not None:
                raise AuthFlowError(
                    "already_authenticated",
                    "Telegram-аккаунт уже подключён.",
                    409,
                )
            if self._challenge is not None:
                raise AuthFlowError(
                    "authentication_in_progress",
                    "Завершите уже начатый вход или дождитесь истечения запроса.",
                    409,
                )

            self._prepare_storage()
            client = self._client_factory(str(self._session_path), api_id, api_hash)
            challenge_id = uuid4().hex
            try:
                await client.connect()
                self._secure_session_files()
                user = await client.get_me()
                if user is not None:
                    account = await self._complete_login(
                        client, api_id, api_hash, user
                    )
                    return AuthStep(challenge_id, "complete", account)

                sent_code = await client.send_code_request(phone)
                phone_code_hash = str(sent_code.phone_code_hash)
                self._challenge = AuthChallenge(
                    challenge_id=challenge_id,
                    client=client,
                    api_id=api_id,
                    api_hash=api_hash,
                    phone=phone,
                    phone_code_hash=phone_code_hash,
                    expires_at=time.monotonic() + self._challenge_ttl,
                )
                return AuthStep(challenge_id, "code")
            except TELETHON_EXCEPTIONS as exc:
                await self._disconnect_safely(client)
                self._raise_telegram_error(exc)

    async def verify_code(self, challenge_id: str, code: str) -> AuthStep:
        async with self._lock:
            challenge = await self._get_challenge(challenge_id)
            try:
                user = await challenge.client.sign_in(
                    phone=challenge.phone,
                    code=code,
                    phone_code_hash=challenge.phone_code_hash,
                )
            except errors.SessionPasswordNeededError:
                return AuthStep(challenge_id, "password")
            except (errors.PhoneCodeExpiredError, errors.PhoneCodeHashEmptyError) as exc:
                await self._drop_challenge()
                self._raise_telegram_error(exc)
            except TELETHON_EXCEPTIONS as exc:
                self._raise_telegram_error(exc)

            account = await self._complete_challenge(challenge, user)
            return AuthStep(challenge_id, "complete", account)

    async def verify_password(self, challenge_id: str, password: str) -> AuthStep:
        async with self._lock:
            challenge = await self._get_challenge(challenge_id)
            try:
                user = await challenge.client.sign_in(password=password)
            except TELETHON_EXCEPTIONS as exc:
                self._raise_telegram_error(exc)

            account = await self._complete_challenge(challenge, user)
            return AuthStep(challenge_id, "complete", account)

    async def logout(self) -> None:
        async with self._lock:
            had_client = self._client is not None or self._challenge is not None
            await self._drop_challenge()
            if self._client is not None:
                await self._disconnect_safely(self._client)
            self._client = None
            self._account = None
            if had_client:
                logger.info("Telegram client disconnected")

    async def close(self) -> None:
        await self.logout()

    async def _complete_challenge(
        self, challenge: AuthChallenge, user: Any
    ) -> AccountInfo:
        if user is None:
            raise AuthFlowError(
                "authentication_failed",
                "Telegram не подтвердил авторизацию.",
                502,
            )
        account = await self._complete_login(
            challenge.client,
            challenge.api_id,
            challenge.api_hash,
            user,
        )
        self._challenge = None
        return account

    async def _complete_login(
        self,
        client: TelegramClientProtocol,
        api_id: int,
        api_hash: str,
        user: Any,
    ) -> AccountInfo:
        account = self._account_from_user(user)
        try:
            self._write_credentials(api_id, api_hash)
        except OSError as exc:
            await self._disconnect_safely(client)
            raise AuthFlowError(
                "storage_unavailable",
                "Не удалось сохранить локальную Telegram-сессию.",
                500,
            ) from exc
        self._secure_session_files()
        self._client = client
        self._account = account
        logger.info("Telegram account connected (user_id=%s)", account.telegram_user_id)
        return account

    async def _get_challenge(self, challenge_id: str) -> AuthChallenge:
        await self._expire_challenge()
        if self._challenge is None or self._challenge.challenge_id != challenge_id:
            raise AuthFlowError(
                "challenge_not_found",
                "Запрос входа не найден. Начните вход заново.",
                404,
            )
        return self._challenge

    async def _expire_challenge(self, *, raise_error: bool = True) -> None:
        if self._challenge and self._challenge.expires_at <= time.monotonic():
            await self._drop_challenge()
            if raise_error:
                raise AuthFlowError(
                    "challenge_expired",
                    "Время входа истекло. Запросите новый код.",
                    410,
                )

    async def _drop_challenge(self) -> None:
        if self._challenge is not None:
            await self._disconnect_safely(self._challenge.client)
            self._challenge = None

    async def _disconnect_safely(self, client: TelegramClientProtocol) -> None:
        try:
            result = client.disconnect()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.warning("Failed to disconnect Telegram client", exc_info=True)

    def _prepare_storage(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._sessions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._set_private_permissions(self._data_dir, 0o700)
        self._set_private_permissions(self._sessions_dir, 0o700)

    def _write_credentials(self, api_id: int, api_hash: str) -> None:
        self._prepare_storage()
        temp_path = self._credentials_path.with_suffix(".tmp")
        payload = {"api_id": api_id, "api_hash": api_hash}
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self._set_private_permissions(temp_path, 0o600)
        os.replace(temp_path, self._credentials_path)
        self._set_private_permissions(self._credentials_path, 0o600)

    def _secure_session_files(self) -> None:
        for path in self._sessions_dir.glob("account.session*"):
            self._set_private_permissions(path, 0o600)

    def _read_credentials(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._credentials_path.read_text(encoding="utf-8"))
            api_id = payload.get("api_id")
            api_hash = payload.get("api_hash")
            if not isinstance(api_id, int) or not isinstance(api_hash, str):
                raise TypeError("invalid credential types")
            return {"api_id": api_id, "api_hash": api_hash}
        except (OSError, TypeError, ValueError):
            logger.error("Cannot read saved Telegram credentials")
            return None

    @staticmethod
    def _set_private_permissions(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except OSError:
            logger.warning("Cannot restrict permissions for %s", path.name)

    @staticmethod
    def _account_from_user(user: Any) -> AccountInfo:
        first_name = str(getattr(user, "first_name", "") or "").strip()
        last_name = str(getattr(user, "last_name", "") or "").strip()
        username_value = getattr(user, "username", None)
        username = str(username_value) if username_value else None
        display_name = " ".join(part for part in (first_name, last_name) if part)
        if not display_name:
            display_name = username or str(user.id)
        return AccountInfo(
            telegram_user_id=int(user.id),
            display_name=display_name,
            username=username,
        )

    @staticmethod
    def _raise_telegram_error(exc: Exception) -> NoReturn:
        if isinstance(exc, AuthFlowError):
            raise exc
        if isinstance(exc, errors.ApiIdInvalidError):
            raise AuthFlowError(
                "api_credentials_invalid",
                "Telegram отклонил api_id или api_hash.",
                400,
            ) from exc
        if isinstance(exc, errors.PhoneNumberInvalidError):
            raise AuthFlowError(
                "phone_invalid", "Telegram отклонил номер телефона.", 400
            ) from exc
        if isinstance(exc, errors.PhoneNumberBannedError):
            raise AuthFlowError(
                "phone_banned", "Этот номер заблокирован Telegram.", 403
            ) from exc
        if isinstance(exc, errors.PhoneNumberFloodError):
            raise AuthFlowError(
                "phone_rate_limited",
                "Слишком много попыток для этого номера. Повторите позже.",
                429,
            ) from exc
        if isinstance(exc, errors.FloodWaitError):
            seconds = max(1, int(exc.seconds))
            raise AuthFlowError(
                "flood_wait",
                f"Telegram ограничил запросы. Повторите через {seconds} сек.",
                429,
                retry_after=seconds,
            ) from exc
        if isinstance(exc, (errors.PhoneCodeEmptyError, errors.PhoneCodeInvalidError)):
            raise AuthFlowError(
                "code_invalid", "Код подтверждения неверен.", 400
            ) from exc
        if isinstance(exc, (errors.PhoneCodeExpiredError, errors.PhoneCodeHashEmptyError)):
            raise AuthFlowError(
                "code_expired",
                "Код подтверждения истёк. Запросите новый код.",
                410,
            ) from exc
        if isinstance(exc, errors.PasswordHashInvalidError):
            raise AuthFlowError(
                "password_invalid", "Пароль двухэтапной проверки неверен.", 400
            ) from exc
        if isinstance(exc, errors.PhoneNumberUnoccupiedError):
            raise AuthFlowError(
                "phone_unregistered",
                "Для номера не найден Telegram-аккаунт.",
                400,
            ) from exc
        if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
            raise AuthFlowError(
                "network_unavailable",
                "Не удалось подключиться к Telegram. Проверьте сеть.",
                503,
            ) from exc
        if isinstance(exc, errors.RPCError):
            raise AuthFlowError(
                "telegram_error",
                "Telegram отклонил запрос авторизации.",
                502,
            ) from exc
        raise AuthFlowError(
            "authentication_failed",
            "Не удалось выполнить авторизацию Telegram.",
            500,
        ) from exc
