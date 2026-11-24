from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
        entities: dict[str, Any] | None = None,
    ) -> None:
        self.dialogs = dialogs
        self.entities = entities or {}

    async def iter_dialogs(
        self, limit: float | None = None
    ) -> AsyncIterator[FakeDialog]:
        for dialog in self.dialogs:
            yield dialog

    async def get_entity(self, entity: str) -> Any:
        try:
            return self.entities[entity.casefold()]
        except KeyError as exc:
            raise ValueError("entity not found") from exc


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


def test_groups_api_lists_and_resolves(tmp_path) -> None:
    dialog = FakeDialog(
        id=-1001,
        name="API group",
        is_group=True,
        entity=SimpleNamespace(
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

    assert groups.status_code == 200
    assert groups.json()["total"] == 1
    assert groups.json()["items"][0]["title"] == "API group"
    assert resolved.status_code == 200
    assert resolved.json()["id"] == -1002
