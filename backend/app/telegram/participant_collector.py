from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol, cast

from telethon import errors

from backend.app.telegram.group_service import GroupServiceError


class ParticipantClientProtocol(Protocol):
    def iter_participants(
        self,
        entity: Any,
        limit: float | None = None,
        *,
        search: str = "",
    ) -> AsyncIterator[Any]: ...


class SessionManagerProtocol(Protocol):
    async def require_client(self) -> Any: ...


class GroupServiceProtocol(Protocol):
    async def get_entity(self, group_id: int) -> Any: ...


@dataclass(frozen=True)
class ParticipantRecord:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_bot: bool


class CollectorError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        wait_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.wait_seconds = wait_seconds


class ParticipantCollector:
    def __init__(
        self,
        session_manager: SessionManagerProtocol,
        group_service: GroupServiceProtocol,
    ) -> None:
        self._session_manager = session_manager
        self._group_service = group_service

    async def collect(self, group_id: int) -> AsyncIterator[ParticipantRecord]:
        client = cast(
            ParticipantClientProtocol,
            await self._session_manager.require_client(),
        )
        try:
            entity = await self._group_service.get_entity(group_id)
            async for user in client.iter_participants(entity):
                yield ParticipantRecord(
                    telegram_user_id=int(user.id),
                    username=self._optional_text(getattr(user, "username", None)),
                    first_name=self._optional_text(getattr(user, "first_name", None)),
                    last_name=self._optional_text(getattr(user, "last_name", None)),
                    is_bot=bool(getattr(user, "bot", False)),
                )
        except GroupServiceError as exc:
            if exc.code in {"group_no_access", "group_not_found"}:
                raise CollectorError(exc.code, exc.message) from exc
            raise CollectorError("telegram_error", exc.message) from exc
        except (
            errors.ChatAdminRequiredError,
            errors.ChannelPrivateError,
            errors.UserNotParticipantError,
        ) as exc:
            raise CollectorError(
                "participants_unavailable",
                "Telegram не разрешает чтение списка участников.",
            ) from exc
        except (errors.RPCError, OSError, TimeoutError, ConnectionError) as exc:
            self._raise_telegram_error(exc)

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _raise_telegram_error(exc: Exception) -> NoReturn:
        if isinstance(exc, errors.FloodWaitError):
            seconds = max(1, int(exc.seconds))
            raise CollectorError(
                "flood_wait",
                f"Telegram ограничил запросы на {seconds} сек.",
                wait_seconds=seconds,
            ) from exc
        if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
            raise CollectorError(
                "network_unavailable",
                "Соединение с Telegram потеряно.",
            ) from exc
        raise CollectorError(
            "telegram_error",
            "Telegram прервал получение участников.",
        ) from exc
