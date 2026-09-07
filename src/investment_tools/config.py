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

# Relative to $HOME, resolved when the config is read rather than at import,
# so importing this module still depends on nothing outside it.
ALLOCATION_RELATIVE = Path(".config/investment-tools/allocation.toml")
HISTORY_DB_RELATIVE = Path(".local/state/investment-tools/history.db")


@dataclass(frozen=True)
class Config:
    """What a depot check needs, whichever front end asked for it."""

    comdirect_client_id: str = field(repr=False)
    comdirect_client_secret: str = field(repr=False)
    comdirect_username: str = field(repr=False)
    comdirect_password: str = field(repr=False)
    allocation_path: Path
    history_db_path: Path


@dataclass(frozen=True)
class TelegramConfig:
    """Only the bot front end needs these, so only it asks for them."""

    bot_token: str = field(repr=False)
    chat_id: int


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is not set")
    return value


def load_config() -> Config:
    home = Path.home()
    return Config(
        comdirect_client_id=_required("COMDIRECT_CLIENT_ID"),
        comdirect_client_secret=_required("COMDIRECT_CLIENT_SECRET"),
        comdirect_username=_required("COMDIRECT_USERNAME"),
        comdirect_password=_required("COMDIRECT_PASSWORD"),
        allocation_path=Path(os.environ.get("ALLOCATION_PATH") or home / ALLOCATION_RELATIVE),
        history_db_path=Path(os.environ.get("HISTORY_DB_PATH") or home / HISTORY_DB_RELATIVE),
    )


def load_telegram_config() -> TelegramConfig:
    """Read the bot settings. Only `investment-tools bot` calls this, so the
    terminal front end runs without a bot token at all."""
    chat_id = _required("TELEGRAM_CHAT_ID")
    try:
        chat_id_int = int(chat_id)
    except ValueError:
        raise ValueError("TELEGRAM_CHAT_ID must be an integer") from None

    return TelegramConfig(bot_token=_required("TELEGRAM_BOT_TOKEN"), chat_id=chat_id_int)


def load_targets(path: Path) -> list[Target]:
    """Read the target allocation.

    The file lives outside the repository: it describes what the owner actually
    holds.
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
