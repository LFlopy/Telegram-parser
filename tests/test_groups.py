from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from telethon import errors

from backend.app.main import create_app
from backend.app.telegram.group_service import GroupServiceError, TelegramGroupService
from backend.app.telegram.session_manager import TelegramSessionManager


@dataclass
class FakeDialog:
    id: int
    name: str
    is_group: bool
    entity: Any


class FakeGroupClient:
    def __init__(
        self,
        dialogs: list[FakeDialog],
        entities: dict[Any, Any] | None = None,
        access_errors: dict[int, Exception] | None = None,
    ) -> None:
        self.dialogs = dialogs
        self.entities = entities or {}
        self.access_errors = access_errors or {}

    async def iter_dialogs(
        self, limit: float | None = None
    ) -> AsyncIterator[FakeDialog]:
        for dialog in self.dialogs:
            yield dialog

    async def get_entity(self, entity: Any) -> Any:
        key = entity.casefold() if isinstance(entity, str) else entity
        try:
            return self.entities[key]
        except KeyError as exc:
            raise ValueError("entity not found") from exc

    async def get_participants(
        self, entity: Any, limit: float | None = None
    ) -> list[Any]:
        group_id = int(getattr(entity, "marked_id"))
        error = self.access_errors.get(group_id)
        if error is not None:
            raise error
        return []


class FakeSessionManager:
    def __init__(self, client: FakeGroupClient) -> None:
        self.client = client

    async def require_client(self) -> FakeGroupClient:
        return self.client


@pytest.mark.asyncio
async def test_list_groups_filters_and_sorts_dialogs() -> None:
    dialogs = [
        FakeDialog(
            id=-1002,
            name="Zulu supergroup",
            is_group=True,
            entity=SimpleNamespace(
                marked_id=-1002,
                title="Zulu supergroup",
                username="zulu_group",
                megagroup=True,
                gigagroup=False,
            ),
        ),
        FakeDialog(
            id=42,
            name="Direct user",
            is_group=False,
            entity=SimpleNamespace(username="person"),
        ),
        FakeDialog(
            id=-101,
            name="Alpha group",
            is_group=True,
            entity=SimpleNamespace(
                marked_id=-101,
                title="Alpha group",
                username=None,
                megagroup=False,
                gigagroup=False,
            ),
        ),
        FakeDialog(
            id=-1003,
            name="Broadcast channel",
            is_group=False,
            entity=SimpleNamespace(
                marked_id=-1003,
                title="Broadcast channel",
                username="news",
                megagroup=False,
                gigagroup=False,
            ),
        ),
    ]
    service = TelegramGroupService(FakeSessionManager(FakeGroupClient(dialogs)))

    groups = await service.list_groups()

    assert [group.title for group in groups] == ["Alpha group", "Zulu supergroup"]
    assert groups[0].group_type == "group"
    assert groups[1].group_type == "supergroup"
    assert groups[1].username == "zulu_group"
    assert groups[1].id == -1002


@pytest.mark.asyncio
async def test_search_pagination_and_public_resolution() -> None:
    dialogs = [
        FakeDialog(
            id=-index,
            name=f"Group {index}",
            is_group=True,
            entity=SimpleNamespace(
                marked_id=-index,
                title=f"Group {index}",
                username=f"team_{index}",
                megagroup=index % 2 == 0,
                gigagroup=False,
            ),
        )
        for index in range(1, 6)
    ]
    public_group = SimpleNamespace(
        marked_id=-100500,
        title="Public team",
        username="public_team",
        megagroup=True,
        gigagroup=False,
        broadcast=False,
    )
    client = FakeGroupClient(dialogs, {"public_team": public_group})
    service = TelegramGroupService(FakeSessionManager(client))

    page = await service.get_page(search="team_", page=2, page_size=2)
    resolved = await service.resolve_public("https://t.me/public_team")

    assert page.total == 5
    assert [group.title for group in page.items] == ["Group 3", "Group 4"]
    assert resolved.id == -100500
    assert resolved.group_type == "supergroup"
    assert resolved.username == "public_team"

    with pytest.raises(GroupServiceError) as invite_error:
        await service.resolve_public("https://t.me/+private-invite")
    assert invite_error.value.code == "public_address_invalid"

    with pytest.raises(GroupServiceError) as missing_error:
        await service.resolve_public("@missing_group")
    assert missing_error.value.code == "group_not_found"


def test_groups_api_lists_and_resolves(tmp_path: Path) -> None:
    dialog = FakeDialog(
        id=-1001,
        name="API group",
        is_group=True,
        entity=SimpleNamespace(
            marked_id=-1001,
            title="API group",
            username="api_group",
            megagroup=True,
            gigagroup=False,
        ),
    )
    public_group = SimpleNamespace(
        marked_id=-1002,
        title="Resolved group",
        username="resolved_group",
        megagroup=True,
        gigagroup=False,
        broadcast=False,
    )
    service = TelegramGroupService(
        FakeSessionManager(
            FakeGroupClient([dialog], {"resolved_group": public_group})
        )
    )
    app = create_app(
        session_manager=TelegramSessionManager(tmp_path),
        group_service=service,
    )

    with TestClient(app) as api:
        groups = api.get("/api/groups", params={"search": "api", "page_size": 10})
        resolved = api.post(
            "/api/groups/resolve",
            json={"link_or_username": "@resolved_group"},
        )
        access = api.get("/api/groups/-1001/access")

    assert groups.status_code == 200
    assert groups.json()["total"] == 1
    assert groups.json()["items"][0]["title"] == "API group"
    assert resolved.status_code == 200
    assert resolved.json()["id"] == -1002
    assert access.status_code == 200
    assert access.json() == {"can_read_members": True, "reason": None}


@pytest.mark.asyncio
async def test_member_access_states() -> None:
    available_entity = SimpleNamespace(
        marked_id=-1001,
        title="Available",
        username="available_group",
        megagroup=True,
        gigagroup=False,
        broadcast=False,
    )
    restricted_entity = SimpleNamespace(
        marked_id=-1002,
        title="Restricted",
        username="restricted_group",
        megagroup=True,
        gigagroup=False,
        broadcast=False,
    )
    client = FakeGroupClient(
        [],
        entities={-1001: available_entity, -1002: restricted_entity},
        access_errors={
            -1002: errors.ChatAdminRequiredError(request=None),
        },
    )
    service = TelegramGroupService(FakeSessionManager(client))

    available = await service.check_access(-1001)
    restricted = await service.check_access(-1002)

    assert available.can_read_members is True
    assert available.reason is None
    assert restricted.can_read_members is False
    assert restricted.reason is not None

    with pytest.raises(GroupServiceError) as missing_error:
        await service.check_access(-9999)
    assert missing_error.value.code == "group_not_found"


def test_group_access_api_handles_restricted_and_missing(tmp_path: Path) -> None:
    restricted_entity = SimpleNamespace(
        marked_id=-1002,
        title="Restricted",
        username="restricted_group",
        megagroup=True,
        gigagroup=False,
        broadcast=False,
    )
    service = TelegramGroupService(
        FakeSessionManager(
            FakeGroupClient(
                [],
                entities={-1002: restricted_entity},
                access_errors={
                    -1002: errors.ChatAdminRequiredError(request=None),
                },
            )
        )
    )
    app = create_app(
        session_manager=TelegramSessionManager(tmp_path),
        group_service=service,
    )

    with TestClient(app) as api:
        restricted = api.get("/api/groups/-1002/access")
        missing = api.get("/api/groups/-9999/access")

    assert restricted.status_code == 200
    assert restricted.json()["can_read_members"] is False
    assert restricted.json()["reason"]
    assert missing.status_code == 404
    assert missing.json()["code"] == "group_not_found"


def test_groups_api_requires_authentication(tmp_path: Path) -> None:
    app = create_app(session_manager=TelegramSessionManager(tmp_path))

    with TestClient(app) as api:
        response = api.get("/api/groups")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"
