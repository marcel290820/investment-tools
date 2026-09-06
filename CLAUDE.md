# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Personal tooling for managing investments. One tool exists per concern; they share
this repo but not a framework.

**First tool: allocation drift bot.** Reads the owner's comdirect depot
read-only, compares it against a target allocation, and reports drift over
Telegram on a `/check` command.

Layering runs one way: `drift` and `report` are pure and import nothing from this
package's edges; `comdirect` and `bot` are the edges; `config` is the boundary
where untrusted input becomes typed values. Keep it that way. Anything that needs
a network to test does not belong in `drift` or `report`.

## This repository is public

Nothing sensitive is ever tracked. Credentials, account numbers, depot IDs, ISINs
tied to real holdings, Telegram chat IDs, and the target allocation itself are read
from the environment or from a file that lives only on the server. Test fixtures use
invented values. `.gitignore` blocks `.env*`, `secrets/`, key material, and `data/`;
a commit hook runs gitleaks on the staged diff.

When a new config value appears, add its name to `.env.example` with an empty value,
never a sample that looks real.

## Stack

Python 3.12. The VPS runs 3.12.3, so that is the floor and the ceiling. Chosen over
Node because every maintained comdirect client is Python and the API is plain REST
with no vendor SDK on either side.

## comdirect API

Official spec (German, 85 pages):
https://kunde.comdirect.de/cms/media/comdirect_REST_API_Dokumentation.pdf
Credentials come from the comdirect developer self-service, separate from the normal
online-banking login.

Endpoints the tracker needs:

- `GET /brokerage/clients/user/v3/depots` lists depots
- `GET /brokerage/v3/depots/{depotId}/positions` returns `DepotPosition[]` plus a
  `DepotAggregation`

`DepotPosition` carries `currentValue` (position value at current prices) and
`purchaseValue`. Allocation math therefore needs no external price feed. Do not add
Yahoo Finance or similar for valuation; the bank already priced the position.

### The authentication constraint

This is the single fact that shapes the whole tool, so do not design around a
schedule that ignores it.

The login is OAuth2 password grant, then a session-status call, then a TAN challenge
that the owner approves by hand in the photoTAN app, then a `CD_SECONDARY` token
upgrade. The access token lives 599 seconds. The spec states the session TAN stays
valid only until the last access/refresh token expires, and requires that any
auto-refresh loop stop when the application stops, which kills the session.

So an unattended daily timer cannot authenticate on its own. The bot therefore runs
on demand: `/check` starts a login, the owner approves the push prompt in the
comdirect photoTAN app, the bot reads the depot and revokes the token. One short
burst per check, no resident session.

photoTAN-Push is the only TAN method this supports. The spec is explicit that push
approval needs no `x-once-authentication` header, so no second factor ever passes
through the bot or through Telegram. Do not add a code-entry path; it would move a
TAN into a chat log.

The activation call answers 422 while the prompt is unanswered, which is
indistinguishable from a rejection. Treat any other status as fatal rather than
retrying, because three bad TAN entries lock online banking.

Read-only means read-only. The API exposes order placement under `/brokerage/v3/orders`.
Nothing in this repo calls it.

## Deployment

Hetzner VPS, Ubuntu 24.04, x86_64, 7.6 GB RAM. Reached over the `hetzner` ssh alias.
No Docker installed, and none is wanted for a job this small.

`deploy/investment-tools.service` follows the pattern already running there at
`/opt/daily-digest`: code in `/opt/<tool>` owned by a dedicated unprivileged user,
a venv, secrets in a root-owned `/etc/<tool>/env` pulled in with `EnvironmentFile`,
and the systemd hardening flags. It differs in one way: the bot listens for a
command, so it is a `Restart=always` service rather than a oneshot plus a timer.

Read `systemctl cat daily-digest@.service` on the VPS before changing the unit.

## Conventions

Money is a decimal amount plus a currency, never a float. Timestamps are stored in
UTC and converted only for display in the Telegram message. The comdirect client and
the Telegram sender are boundary code; drift calculation takes positions and a target
allocation as plain values and needs no network to test.

## Commands

`./.claude/check.sh` runs ruff, ruff format, mypy strict and pytest. CI runs the
same script, and so does the commit gate, so a green run locally means a green run
everywhere. Run a single test file with `pytest tests/test_drift.py`.

Dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, both
generated with `uv pip compile` from `pyproject.toml`. Regenerate them in the same
change that edits a dependency.
