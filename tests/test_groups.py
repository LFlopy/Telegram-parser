from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.telegram.group_service import TelegramGroupService


@dataclass
class FakeDialog:
    id: int
    name: str
    is_group: bool
    entity: Any


class FakeGroupClient:
    def __init__(self, dialogs: list[FakeDialog]) -> None:
        self.dialogs = dialogs

    async def iter_dialogs(
        self, limit: float | None = None
    ) -> AsyncIterator[FakeDialog]:
        for dialog in self.dialogs:
            yield dialog


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
