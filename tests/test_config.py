from decimal import Decimal
from pathlib import Path

import pytest

from investment_tools.config import load_targets


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "allocation.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_valid_file_parses(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        [[position]]
        wkn = "aaa111"
        name = "Fund A"
        share_pct = 62.5

        [[position]]
        wkn = "BBB222"
        name = "Fund B"
        share_pct = 37.5
        """,
    )
    targets = load_targets(path)
    assert [t.wkn for t in targets] == ["AAA111", "BBB222"]
    assert targets[0].share_pct == Decimal("62.5")


def test_shares_keep_full_precision(tmp_path: Path) -> None:
    # Read via str() so a share like 18.75 does not arrive as a binary float.
    path = write(tmp_path, '[[position]]\nwkn = "AAA"\nshare_pct = 18.75\n')
    assert load_targets(path)[0].share_pct == Decimal("18.75")


def test_a_duplicate_wkn_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[position]]\nwkn = "AAA"\nshare_pct = 50\n[[position]]\nwkn = "aaa"\nshare_pct = 50\n',
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_targets(path)


def test_an_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="defines no"):
        load_targets(write(tmp_path, ""))


def test_an_out_of_range_share_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, '[[position]]\nwkn = "AAA"\nshare_pct = 0\n')
    with pytest.raises(ValueError, match="between 0 and 100"):
        load_targets(path)


def test_a_missing_share_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no share_pct"):
        load_targets(write(tmp_path, '[[position]]\nwkn = "AAA"\n'))
