"""Tests for the parts of the bank client that must not be got wrong.

The token comdirect issues carries BROKERAGE_RW, so the only thing standing
between a finished read and a session that could trade is the revoke call.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from investment_tools.comdirect import REVOKE_URL, ComdirectError, ComdirectSession


@pytest.fixture
def calls() -> list[httpx.Request]:
    return []


def logged_in(handler: Callable[[httpx.Request], httpx.Response]) -> ComdirectSession:
    """A session that has already authenticated, talking to a fake bank."""
    from investment_tools.comdirect import _Tokens

    bank = ComdirectSession(
        "id",
        "secret",
        "user",
        "pin",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    bank._tokens = _Tokens(access="access-token", refresh="refresh-token")
    return bank


@pytest.mark.asyncio
async def test_revoke_sends_a_delete_with_the_bearer_token(calls: list[httpx.Request]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    bank = logged_in(handler)
    await bank.revoke()

    assert len(calls) == 1
    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == REVOKE_URL
    assert calls[0].headers["Authorization"] == "Bearer access-token"
    assert bank.revoked


@pytest.mark.asyncio
async def test_anything_but_204_means_the_session_is_still_live() -> None:
    # The spec returns 204 on success. Treating a 4xx as good would leave a
    # token that can trade alive for the rest of its ten minutes.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    bank = logged_in(handler)

    with pytest.raises(ComdirectError, match="expected 204"):
        await bank.revoke()
    assert not bank.revoked


@pytest.mark.asyncio
async def test_a_failed_revoke_does_not_leave_the_token_in_place() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    bank = logged_in(handler)
    with pytest.raises(ComdirectError):
        await bank.revoke()

    with pytest.raises(ComdirectError, match="not authenticated"):
        await bank.positions("depot-1")


@pytest.mark.asyncio
async def test_leaving_the_context_revokes(calls: list[httpx.Request]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    async with logged_in(handler) as bank:
        pass

    assert [c.method for c in calls] == ["DELETE"]
    assert bank.revoked


@pytest.mark.asyncio
async def test_the_session_is_revoked_even_when_the_reads_blow_up(
    calls: list[httpx.Request],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    with pytest.raises(RuntimeError):
        async with logged_in(handler) as bank:
            raise RuntimeError("depot read failed")

    assert [c.method for c in calls] == ["DELETE"]
    assert bank.revoked


@pytest.mark.asyncio
async def test_a_failing_revoke_does_not_mask_the_original_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(RuntimeError, match="depot read failed"):
        async with logged_in(handler) as bank:
            raise RuntimeError("depot read failed")

    assert not bank.revoked  # and the caller can see the session outlived us
