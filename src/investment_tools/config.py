"""Configuration, read once at the boundary.

Everything here comes from outside the program and is therefore suspect until
checked. Past this module the rest of the code trusts its types.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .drift import Target

DEFAULT_ALLOCATION_PATH = Path("/etc/investment-tools/allocation.toml")


@dataclass(frozen=True)
class Config:
    comdirect_client_id: str = field(repr=False)
    comdirect_client_secret: str = field(repr=False)
    comdirect_username: str = field(repr=False)
    comdirect_password: str = field(repr=False)
    telegram_bot_token: str = field(repr=False)
    telegram_chat_id: int
    allocation_path: Path


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is not set")
    return value


def load_config() -> Config:
    chat_id = _required("TELEGRAM_CHAT_ID")
    try:
        chat_id_int = int(chat_id)
    except ValueError:
        raise ValueError("TELEGRAM_CHAT_ID must be an integer") from None

    return Config(
        comdirect_client_id=_required("COMDIRECT_CLIENT_ID"),
        comdirect_client_secret=_required("COMDIRECT_CLIENT_SECRET"),
        comdirect_username=_required("COMDIRECT_USERNAME"),
        comdirect_password=_required("COMDIRECT_PASSWORD"),
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=chat_id_int,
        allocation_path=Path(os.environ.get("ALLOCATION_PATH") or DEFAULT_ALLOCATION_PATH),
    )


def load_targets(path: Path) -> list[Target]:
    """Read the target allocation.

    The file lives on the server, never in the repository: it describes what the
    owner actually holds.
    """
    with path.open("rb") as handle:
        document = tomllib.load(handle)

    entries = document.get("position")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path} defines no [[position]] entries")

    targets = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        wkn = str(entry.get("wkn", "")).strip().upper()
        name = str(entry.get("name", "")).strip()
        share = entry.get("share_pct")
        if not wkn:
            raise ValueError(f"{path}: position {index} has no wkn")
        if wkn in seen:
            raise ValueError(f"{path}: duplicate wkn {wkn}")
        if share is None:
            raise ValueError(f"{path}: position {wkn} has no share_pct")
        try:
            share_pct = Decimal(str(share))
        except InvalidOperation:
            raise ValueError(f"{path}: position {wkn} has a non-numeric share_pct") from None
        if not 0 < share_pct < 100:
            raise ValueError(f"{path}: position {wkn} share_pct must be between 0 and 100")
        seen.add(wkn)
        targets.append(Target(wkn=wkn, name=name or wkn, share_pct=share_pct))

    return targets
