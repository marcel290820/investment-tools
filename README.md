# investment-tools

Personal tooling for managing investments. One tool per concern; they share a
repository, not a framework.

## Allocation drift bot

Reads a comdirect depot, compares it against a target allocation, and reports
which positions have wandered far enough to be worth acting on.

You trigger it with `/check` in Telegram. It is not on a timer, because
comdirect has no unattended login: every API session starts with a two-factor
approval, and the session dies with its tokens roughly ten minutes later. With
photoTAN-Push you never type a TAN. The bank pushes a prompt to the photoTAN
app, you approve it there, and the bot continues. No second factor passes
through Telegram.

The depot is only ever read. Nothing here places an order.

### Tolerance bands

A position is flagged once it moves either 5 percentage points or a quarter of
its own target away from where it belongs, whichever comes first. Wide bands are
the point: a rebalance in a German depot realises a capital gain and costs tax,
so the bot is built to stay quiet through normal market noise and speak up only
when the allocation has genuinely shifted.

When something is out of band, the suggestion is to buy, not to sell. The report
says how much new money each underweight position needs to reach its target, and
which positions to pause contributions to. Selling is left to you. The bot never
moves money and has no command that could.

### History

Every check is written to a SQLite file, so the report can say how long a
position has been out of band rather than only that it is out today. Drift that
has held for months reads differently from drift that appeared this morning, and
one snapshot cannot tell you which you are looking at.

### Target allocation

The bands are derived, not configured. The only thing you set is the targets, in
a TOML file that lives on the server and never enters this repository, because it
describes real holdings. `deploy/allocation.example.toml` shows the shape.

## Development

```sh
uv venv .venv && . .venv/bin/activate
uv pip install -e ".[dev]"
./.claude/check.sh          # lint, typecheck, tests
pytest tests/test_drift.py  # one file
```

The drift calculation and the report formatting are pure functions and are
tested directly. The comdirect and Telegram layers hold no logic worth testing
without a live account.

## Deployment

Runs on a VPS as a systemd service. See `deploy/investment-tools.service`, which
carries the install commands in its header.

## Secrets

This repository is public. Credentials, account identifiers, chat ids, and the
target allocation are read from the environment or from root-owned files on the
server. `.env.example` lists the variable names and nothing else.
