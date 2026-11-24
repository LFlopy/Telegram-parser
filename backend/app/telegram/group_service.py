from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any, Literal, NoReturn, Protocol, cast

from telethon import errors, utils

PUBLIC_GROUP_PATTERN = re.compile(
    r"^(?:(?:https?://)?(?:t\.me|telegram\.me)/)?@?"
    r"([A-Za-z][A-Za-z0-9_]{3,31})/?$",
    re.IGNORECASE,
)


class GroupClientProtocol(Protocol):
    def iter_dialogs(self, limit: float | None = None) -> AsyncIterator[Any]: ...

    async def get_entity(self, entity: Any) -> Any: ...

    async def get_participants(self, entity: Any, limit: float | None = None) -> Any: ...


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


@dataclass(frozen=True)
class GroupPage:
    items: list[GroupInfo]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class GroupAccess:
    can_read_members: bool | None
    reason: str | None


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
        except (errors.RPCError, OSError, TimeoutError, ConnectionError) as exc:
            self._raise_telegram_error(exc)

        return sorted(groups, key=lambda group: (group.title.casefold(), group.id))

    async def get_page(
        self,
        *,
        search: str | None,
        page: int,
        page_size: int,
    ) -> GroupPage:
        groups = await self.list_groups()
        query = (search or "").strip().casefold()
        if query:
            groups = [
                group
                for group in groups
                if query in group.title.casefold()
                or (group.username is not None and query in group.username.casefold())
            ]
        total = len(groups)
        start = (page - 1) * page_size
        return GroupPage(
            items=groups[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def resolve_public(self, link_or_username: str) -> GroupInfo:
        username = self._public_username(link_or_username)
        client = cast(
            GroupClientProtocol,
            await self._session_manager.require_client(),
        )
        try:
            entity = await client.get_entity(username)
        except (
            errors.UsernameInvalidError,
            errors.UsernameNotOccupiedError,
            ValueError,
        ) as exc:
            raise GroupServiceError(
                "group_not_found",
                "Публичная группа не найдена.",
                404,
            ) from exc
        except (errors.RPCError, OSError, TimeoutError, ConnectionError) as exc:
            self._raise_telegram_error(exc)

        if not self._is_group_entity(entity):
            raise GroupServiceError(
                "not_a_group",
                "Указанный адрес не относится к группе или супергруппе.",
                400,
            )

        group_id = self._marked_id(entity)
        group_type: Literal["group", "supergroup"] = (
            "supergroup"
            if bool(getattr(entity, "megagroup", False))
            or bool(getattr(entity, "gigagroup", False))
            else "group"
        )
        resolved_username = getattr(entity, "username", None)
        previous = self._groups.get(group_id)
        group = GroupInfo(
            id=group_id,
            telegram_group_id=group_id,
            title=str(getattr(entity, "title", None) or username),
            username=str(resolved_username) if resolved_username else username,
            group_type=group_type,
            access_state=previous.access_state if previous else "unknown",
        )
        self._entities[group_id] = entity
        self._groups[group_id] = group
        return group

    async def check_access(self, group_id: int) -> GroupAccess:
        client = cast(
            GroupClientProtocol,
            await self._session_manager.require_client(),
        )
        entity = self._entities.get(group_id)
        if entity is None:
            try:
                entity = await client.get_entity(group_id)
            except (ValueError, errors.ChannelInvalidError) as exc:
                raise GroupServiceError(
                    "group_not_found",
                    "Группа не найдена в доступных диалогах.",
                    404,
                ) from exc
            except (errors.RPCError, OSError, TimeoutError, ConnectionError) as exc:
                self._raise_telegram_error(exc)
            if not self._is_group_entity(entity):
                raise GroupServiceError(
                    "group_not_found",
                    "Группа не найдена в доступных диалогах.",
                    404,
                )
            self._entities[group_id] = entity

        try:
            await client.get_participants(entity, limit=1)
        except (errors.ChatAdminRequiredError, errors.ChannelPrivateError):
            self._set_access_state(group_id, "no_access")
            return GroupAccess(
                can_read_members=False,
                reason="Telegram не разрешает чтение списка участников.",
            )
        except (errors.RPCError, OSError, TimeoutError, ConnectionError) as exc:
            self._raise_telegram_error(exc)

        self._set_access_state(group_id, "available")
        return GroupAccess(can_read_members=True, reason=None)

    def _set_access_state(
        self,
        group_id: int,
        access_state: Literal["available", "no_access"],
    ) -> None:
        group = self._groups.get(group_id)
        if group is not None:
            self._groups[group_id] = replace(group, access_state=access_state)

    @staticmethod
    def _public_username(value: str) -> str:
        match = PUBLIC_GROUP_PATTERN.fullmatch(value.strip())
        if match is None:
            raise GroupServiceError(
                "public_address_invalid",
                "Укажите публичный @username или ссылку t.me/username.",
                422,
            )
        return match.group(1)

    @staticmethod
    def _is_group_entity(entity: Any) -> bool:
        if not hasattr(entity, "title"):
            return False
        is_supergroup = bool(getattr(entity, "megagroup", False)) or bool(
            getattr(entity, "gigagroup", False)
        )
        is_broadcast = bool(getattr(entity, "broadcast", False))
        return is_supergroup or not is_broadcast

    @staticmethod
    def _marked_id(entity: Any) -> int:
        marked_id = getattr(entity, "marked_id", None)
        return int(marked_id if marked_id is not None else utils.get_peer_id(entity))

    @staticmethod
    def _raise_telegram_error(exc: Exception) -> NoReturn:
        if isinstance(exc, errors.FloodWaitError):
            seconds = max(1, int(exc.seconds))
            raise GroupServiceError(
                "flood_wait",
                f"Telegram ограничил запросы. Повторите через {seconds} сек.",
                429,
                retry_after=seconds,
            ) from exc
        if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
            raise GroupServiceError(
                "network_unavailable",
                "Не удалось загрузить группы. Проверьте сеть.",
                503,
            ) from exc
        raise GroupServiceError(
            "telegram_error",
            "Telegram не вернул данные группы.",
            502,
        ) from exc
