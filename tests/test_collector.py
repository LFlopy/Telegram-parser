from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from telethon import errors

from backend.app.telegram.participant_collector import (
    CollectorError,
    ParticipantCollector,
)


class FakeParticipantClient:
    def __init__(
        self,
        users: list[Any],
        error: Exception | None = None,
    ) -> None:
        self.users = users
        self.error = error

    def iter_participants(
        self,
        entity: Any,
        limit: float | None = None,
        *,
        search: str = "",
    ) -> AsyncIterator[Any]:
        async def iterator() -> AsyncIterator[Any]:
            for user in self.users:
                yield user
            if self.error is not None:
                raise self.error

        return iterator()


class FakeSessionManager:
    def __init__(self, client: FakeParticipantClient) -> None:
        self.client = client

    async def require_client(self) -> FakeParticipantClient:
        return self.client


class FakeGroupService:
    async def get_entity(self, group_id: int) -> object:
        return object()


@pytest.mark.asyncio
async def test_collector_streams_normalized_participants() -> None:
    client = FakeParticipantClient(
        [
            SimpleNamespace(
                id=101,
                username=" first_user ",
                first_name=" First ",
                last_name=None,
                bot=False,
            ),
            SimpleNamespace(
                id=102,
                username=None,
                first_name=None,
                last_name="Bot",
                bot=True,
            ),
        ]
    )
    collector = ParticipantCollector(
        FakeSessionManager(client),
        FakeGroupService(),
    )

    records = [record async for record in collector.collect(-1001)]

    assert records[0].telegram_user_id == 101
    assert records[0].username == "first_user"
    assert records[0].first_name == "First"
    assert records[1].is_bot is True


@pytest.mark.asyncio
async def test_collector_reports_flood_wait() -> None:
    collector = ParticipantCollector(
        FakeSessionManager(
            FakeParticipantClient(
                [],
                errors.FloodWaitError(request=None, capture=37),
            )
        ),
        FakeGroupService(),
    )

    with pytest.raises(CollectorError) as error:
        _ = [record async for record in collector.collect(-1001)]

    assert error.value.code == "flood_wait"
    assert error.value.wait_seconds == 37


@pytest.mark.asyncio
async def test_collector_reports_hidden_members() -> None:
    collector = ParticipantCollector(
        FakeSessionManager(
            FakeParticipantClient(
                [],
                errors.ChatAdminRequiredError(request=None),
            )
        ),
        FakeGroupService(),
    )

    with pytest.raises(CollectorError) as error:
        _ = [record async for record in collector.collect(-1001)]

    assert error.value.code == "participants_unavailable"
