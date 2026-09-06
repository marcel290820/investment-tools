"""Entry point: python -m investment_tools"""

from __future__ import annotations

import logging
import sys

from .bot import run
from .config import load_config, load_targets


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    try:
        config = load_config()
        targets = load_targets(config.allocation_path)
    except (OSError, ValueError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1

    run(config, targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
