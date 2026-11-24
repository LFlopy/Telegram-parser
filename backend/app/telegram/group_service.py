from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from telethon import errors

class GroupClientProtocol(Protocol):
    def iter_dialogs(self, limit: float | None = None) -> AsyncIterator[Any]: ...


class SessionManagerProtocol(Protocol):
    async def require_client(self) -> Any: ...


@dataclass(frozen=True)
class GroupInfo:
    id: int
    telegram_group_id: int
    title: str
    username: str | None
    group_type: Literal["group", "supergroup"]
    access_state: Literal["unknown", "available", "no_access"] = "unknown"


class GroupServiceError(Exception):
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


class TelegramGroupService:
    def __init__(self, session_manager: SessionManagerProtocol) -> None:
        self._session_manager = session_manager
        self._entities: dict[int, Any] = {}
        self._groups: dict[int, GroupInfo] = {}

    async def list_groups(self) -> list[GroupInfo]:
        client = cast(
            GroupClientProtocol,
            await self._session_manager.require_client(),
        )
        groups: list[GroupInfo] = []
        try:
            async for dialog in client.iter_dialogs():
                if not bool(getattr(dialog, "is_group", False)):
                    continue
                entity = dialog.entity
                group_id = int(dialog.id)
                group_type: Literal["group", "supergroup"] = (
                    "supergroup"
                    if bool(getattr(entity, "megagroup", False))
                    or bool(getattr(entity, "gigagroup", False))
                    else "group"
                )
                username_value = getattr(entity, "username", None)
                username = str(username_value) if username_value else None
                title_value = getattr(dialog, "name", None) or getattr(
                    entity, "title", None
                )
                previous = self._groups.get(group_id)
                group = GroupInfo(
                    id=group_id,
                    telegram_group_id=group_id,
                    title=str(title_value or group_id),
                    username=username,
                    group_type=group_type,
                    access_state=previous.access_state if previous else "unknown",
                )
                self._entities[group_id] = entity
                self._groups[group_id] = group
                groups.append(group)
        except errors.FloodWaitError as exc:
            seconds = max(1, int(exc.seconds))
            raise GroupServiceError(
                "flood_wait",
                f"Telegram ограничил запросы. Повторите через {seconds} сек.",
                429,
                retry_after=seconds,
            ) from exc
        except (OSError, TimeoutError, ConnectionError) as exc:
            raise GroupServiceError(
                "network_unavailable",
                "Не удалось загрузить группы. Проверьте сеть.",
                503,
            ) from exc
        except errors.RPCError as exc:
            raise GroupServiceError(
                "telegram_error",
                "Telegram не вернул список групп.",
                502,
            ) from exc

        return sorted(groups, key=lambda group: (group.title.casefold(), group.id))
