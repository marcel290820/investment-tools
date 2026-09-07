"""comdirect REST API client, read-only.

Specification (German):
https://kunde.comdirect.de/cms/media/comdirect_REST_API_Dokumentation.pdf

The API has no unattended login. Every session begins with a two-factor step the
owner approves by hand, and the session dies with its tokens, so this client is
built for one short burst of work: log in, read the depot, revoke, exit.

With photoTAN-Push no TAN is ever typed. The bank pushes a prompt to the
comdirect photoTAN app and the activation call carries only the challenge id, so
no second factor passes through this program or through Telegram.

This module talks only to the brokerage read endpoints. The order endpoints under
/brokerage/v3/orders exist and are deliberately not called from anywhere.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .drift import Position

logger = logging.getLogger(__name__)

API_ROOT = "https://api.comdirect.de"
TOKEN_URL = f"{API_ROOT}/oauth/token"
REVOKE_URL = f"{API_ROOT}/oauth/revoke"
API_PREFIX = f"{API_ROOT}/api"

TAN_TYPE = "P_TAN_PUSH"
REQUEST_TIMEOUT_SECONDS = 30.0

# How long to wait for the owner to reach for their phone, and how often to ask
# the bank whether they have. The bank locks online banking after three bad TAN
# entries; push approval submits no TAN, so polling the activation cannot burn
# an attempt, but the poll stays slow and bounded regardless.
APPROVAL_TIMEOUT_SECONDS = 180.0
APPROVAL_POLL_SECONDS = 3.0


class ComdirectError(RuntimeError):
    """The bank refused, or answered with something this client cannot use."""


@dataclass(frozen=True)
class _Tokens:
    access: str
    refresh: str


def _request_id() -> str:
    """Nine digits, unique within a session. The spec suggests HHmmssSSS."""
    return datetime.now(UTC).strftime("%H%M%S") + f"{datetime.now(UTC).microsecond // 1000:03d}"


def _amount(field: Any, *, context: str) -> Decimal:
    """Read an $AmountValue, which the API sends as {"value": ..., "unit": ...}."""
    if not isinstance(field, dict) or "value" not in field:
        raise ComdirectError(f"{context}: expected an amount object, got {field!r}")
    unit = field.get("unit")
    if unit != "EUR":
        raise ComdirectError(f"{context}: expected EUR, got {unit!r}")
    try:
        return Decimal(str(field["value"]))
    except InvalidOperation:
        raise ComdirectError(f"{context}: {field['value']!r} is not a number") from None


class ComdirectSession:
    """One authenticated burst of reads. Use as an async context manager."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self._http = http or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
        self._owns_http = http is None
        self._session_id = secrets.token_hex(16)
        self._tokens: _Tokens | None = None
        self._bank_session: str | None = None
        self.revoked = False
        """True once the bank has confirmed the session is dead."""

    async def __aenter__(self) -> ComdirectSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        # The token this holds can trade, so it is revoked the moment the reads
        # are done rather than left to expire. A failure here must not mask the
        # caller's own exception, but it must not vanish either: callers read
        # `revoked` to find out whether the session is actually dead.
        try:
            await self.revoke()
        except (ComdirectError, httpx.HTTPError) as error:
            logger.error("could not revoke the bank session: %s", error)
        finally:
            if self._owns_http:
                await self._http.aclose()

    def _bank_session_id(self) -> str:
        if self._bank_session is None:
            raise ComdirectError("login has not been started")
        return self._bank_session

    @property
    def _access_token(self) -> str:
        if self._tokens is None:
            raise ComdirectError("not authenticated")
        return self._tokens.access

    def _headers(self, **extra: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "x-http-request-info": json.dumps(
                {
                    "clientRequestId": {
                        "sessionId": self._session_id,
                        "requestId": _request_id(),
                    }
                }
            ),
        }
        headers.update(extra)
        return headers

    async def _token_request(self, form: dict[str, str]) -> _Tokens:
        response = await self._http.post(
            TOKEN_URL,
            data=form,
            headers={"Accept": "application/json"},
        )
        if response.status_code != httpx.codes.OK:
            # The body echoes the grant type and may quote credentials, so only
            # the status is safe to surface.
            raise ComdirectError(
                f"token request '{form['grant_type']}' failed with HTTP {response.status_code}"
            )
        payload = response.json()
        try:
            return _Tokens(access=payload["access_token"], refresh=payload["refresh_token"])
        except KeyError as exc:
            raise ComdirectError(f"token response is missing {exc}") from None

    async def start_login(self) -> str:
        """Authenticate and ask the bank to push a TAN prompt to the app.

        Returns the challenge id needed to activate the session once the owner
        has approved it.
        """
        self._tokens = await self._token_request(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
            }
        )

        response = await self._http.get(
            f"{API_PREFIX}/session/clients/user/v1/sessions",
            headers=self._headers(),
        )
        if response.status_code != httpx.codes.OK:
            raise ComdirectError(f"session lookup failed with HTTP {response.status_code}")
        sessions = response.json()
        if not sessions:
            raise ComdirectError("bank returned no session")
        self._bank_session = sessions[0]["identifier"]

        response = await self._http.post(
            f"{API_PREFIX}/session/clients/user/v1/sessions/{self._bank_session_id()}/validate",
            headers=self._headers(
                **{
                    "Content-Type": "application/json",
                    "x-once-authentication-info": json.dumps({"typ": TAN_TYPE}),
                }
            ),
            json={
                "identifier": self._bank_session_id(),
                "sessionTanActive": True,
                "activated2FA": True,
            },
        )
        if response.status_code != httpx.codes.CREATED:
            raise ComdirectError(f"TAN challenge failed with HTTP {response.status_code}")

        info = response.headers.get("x-once-authentication-info")
        if not info:
            raise ComdirectError("bank did not return a TAN challenge")
        challenge = json.loads(info)
        if challenge.get("typ") != TAN_TYPE:
            raise ComdirectError(
                f"bank offered {challenge.get('typ')!r} instead of push approval; "
                "set photoTAN-Push as the preferred TAN method in online banking"
            )
        return str(challenge["id"])

    async def await_approval(self, challenge_id: str) -> None:
        """Block until the owner approves the push prompt, then take the session.

        The bank answers the activation with 422 while the prompt is still
        pending, so a rejected activation is not distinguishable from an
        unanswered one. Anything other than success or 422 is treated as fatal
        rather than retried.
        """
        deadline = asyncio.get_running_loop().time() + APPROVAL_TIMEOUT_SECONDS
        last_status: int | None = None

        while asyncio.get_running_loop().time() < deadline:
            response = await self._http.patch(
                f"{API_PREFIX}/session/clients/user/v1/sessions/{self._bank_session_id()}",
                headers=self._headers(
                    **{
                        "Content-Type": "application/json",
                        "x-once-authentication-info": json.dumps({"id": challenge_id}),
                    }
                ),
                json={
                    "identifier": self._bank_session_id(),
                    "sessionTanActive": True,
                    "activated2FA": True,
                },
            )
            last_status = response.status_code
            if response.status_code == httpx.codes.OK:
                self._tokens = await self._token_request(
                    {
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "cd_secondary",
                        "token": self._access_token,
                    }
                )
                return
            if response.status_code != httpx.codes.UNPROCESSABLE_ENTITY:
                raise ComdirectError(f"session activation failed with HTTP {response.status_code}")
            await asyncio.sleep(APPROVAL_POLL_SECONDS)

        raise ComdirectError(
            f"no approval within {APPROVAL_TIMEOUT_SECONDS:.0f}s (last HTTP {last_status})"
        )

    async def _get(self, path: str, **params: str) -> Any:
        response = await self._http.get(
            f"{API_PREFIX}{path}", headers=self._headers(), params=params
        )
        if response.status_code != httpx.codes.OK:
            raise ComdirectError(f"GET {path} failed with HTTP {response.status_code}")
        return response.json()

    async def depot_ids(self) -> list[str]:
        payload = await self._get("/brokerage/clients/user/v3/depots")
        return [depot["depotId"] for depot in payload.get("values", [])]

    async def positions(self, depot_id: str) -> list[Position]:
        payload = await self._get(
            f"/brokerage/v3/depots/{depot_id}/positions", **{"with-attr": "instrument"}
        )
        positions = []
        for entry in payload.get("values", []):
            wkn = entry.get("wkn")
            if not wkn:
                raise ComdirectError(f"depot {depot_id} returned a position without a WKN")
            instrument = entry.get("instrument") or {}
            positions.append(
                Position(
                    wkn=str(wkn).upper(),
                    name=str(instrument.get("name") or instrument.get("shortName") or wkn),
                    value_eur=_amount(entry.get("currentValue"), context=f"position {wkn}"),
                )
            )
        return positions

    async def all_positions(self) -> list[Position]:
        """Every position across every depot, merged by instrument."""
        merged: dict[str, Position] = {}
        for depot_id in await self.depot_ids():
            for position in await self.positions(depot_id):
                existing = merged.get(position.wkn)
                merged[position.wkn] = (
                    position
                    if existing is None
                    else Position(
                        wkn=position.wkn,
                        name=existing.name,
                        value_eur=existing.value_eur + position.value_eur,
                    )
                )
        return list(merged.values())

    async def revoke(self) -> None:
        """Invalidate the access token, refresh token and session TAN.

        The spec returns 204 on success and says all three die together. Any
        other status means the session is still live and still able to trade
        until it expires, so it is an error rather than something to shrug at.
        """
        if self._tokens is None:
            self.revoked = True
            return
        token = self._access_token
        # Cleared first: whatever the bank answers, this object must not keep
        # using a token it has just tried to throw away.
        self._tokens = None
        response = await self._http.delete(REVOKE_URL, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != httpx.codes.NO_CONTENT:
            raise ComdirectError(f"revoke returned HTTP {response.status_code}, expected 204")
        self.revoked = True
