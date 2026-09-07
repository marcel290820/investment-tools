# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Personal tooling for managing investments. One tool exists per concern; they share
this repo but not a framework.

**First tool: allocation drift tracker.** Reads the owner's comdirect depot
read-only, compares it against a target allocation, and reports drift. It runs
on the owner's laptop, not on a server, and has two front ends: `investment-tools
check` in a terminal and `/check` in Telegram.

Layering runs one way: `drift` and `report` are pure and import nothing from this
package's edges; `checker` orchestrates one check without knowing who asked;
`comdirect`, `history`, `bot` and `__main__` are the edges; `config` is the
boundary where untrusted input becomes typed values. Keep it that way. Anything
that needs a network or a file to test does not belong in `drift` or `report`,
which is why `format_report` takes breach runs as an argument instead of querying
for them.

`DepotChecker.check` returns the report and sends only progress through its `say`
callback. That split is what lets the terminal put the report on stdout and the
"approve the prompt" line on stderr. Do not collapse it by having the checker
print.

`format_report` emits plain text with no markup. Telegram needs a monospace block
and HTML escaping, so `bot` adds both; a terminal needs neither. Fund names come
from the bank, so any front end that renders markup escapes them.

`history` is a SQLite file holding one row per position per check. Amounts and
shares are stored as text: a value written through a float and read back is no
longer the number that was measured. It is also a record of real holdings, so it
lives at `~/.local/state/investment-tools/history.db` and never in the repository.

The tool reads. Neither front end has a command that allocates, transfers or
orders, and adding one is a decision the owner makes, not a natural next feature.

## This repository is public

Nothing sensitive is ever tracked. Credentials, account numbers, depot IDs, ISINs
tied to real holdings, Telegram chat IDs, and the target allocation itself are read
from the environment or from files under `~/.config/investment-tools`, mode 600.
Test fixtures use invented values. `.gitignore` blocks `.env*`, `secrets/`, key
material, and `data/`; a commit hook runs gitleaks on the staged diff.

When a new config value appears, add its name to `.env.example` with an empty value,
never a sample that looks real.

## Stack

Python 3.12, pinned in `pyproject.toml` and matched by CI. Chosen over Node because
every maintained comdirect client is Python and the API is plain REST with no vendor
SDK on either side. Nothing here needs a newer interpreter, so the pin only moves
when there is a reason to move it, and the lockfiles get regenerated in the same
change.

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

So an unattended daily timer cannot authenticate on its own. The tool therefore runs
on demand: a check starts a login, the owner approves the push prompt in the
comdirect photoTAN app, the tool reads the depot and revokes the token. One short
burst per check, no resident session.

photoTAN-Push is the only TAN method this supports. The spec is explicit that push
approval needs no `x-once-authentication` header, so no second factor ever passes
through this program, through Telegram or through a shell history. Do not add a
code-entry path.

**The approval cannot be polled, and this was learned the hard way.** The spec
documents only 200 and 422 for the activation call. In practice, with
photoTAN-Push the bank answers **400** for as long as the approval has not
reached it, which is the same answer it gives a malformed request. There is
therefore no status that means "still waiting", and an earlier version of this
code polled on 422 and died 66 ms into the first check.

So a person tells the tool when the app accepted it: Enter in the terminal,
`/done` in Telegram. The activation then goes out exactly once. Do not
reintroduce a retry loop.

Three counters make retrying expensive, all from the spec:

- five TAN challenges without one being spent locks online banking
- three wrong TAN entries locks online banking
- a challenge cannot be activated twice, so 2.3 and 2.4 are one pair

Every failed check costs one of those five challenges. Get a change right before
running it against the real account.

Read-only means read-only. The API exposes order placement under `/brokerage/v3/orders`.
Nothing in this repo calls it.

That is not the whole guarantee, because the scope comdirect hands back is
`BANKING_RO BROKERAGE_RW SESSION_RW`: the token this bot holds *can* trade, and
once a session TAN is active further operations need no new TAN. So the session
is revoked as soon as the reads finish rather than left to expire. `DELETE
/oauth/revoke` answers 204 and kills the access token, the refresh token and the
session TAN together; any other status means the session is still live, so it
raises. `ComdirectSession.revoked` records whether the bank confirmed it, and the
bot tells the owner when it did not. Do not weaken that call into a best-effort
fire-and-forget.

## Deployment

The owner's laptop, macOS. It ran on a Hetzner VPS for one day and was taken off
again: a bank credential on a rented box in a shared account bought nothing, since
the checks are manual anyway and a laptop that is closed is a laptop nothing can
reach. Do not propose moving it back.

The venv lives in the repository, config and secrets in `~/.config/investment-tools`
at mode 600, the history database in `~/.local/state/investment-tools`. The CLI is
the primary interface and needs no supervisor. `deploy/com.investment-tools.bot.plist`
is a launchd agent for the Telegram bot alone, and only for the owner who wants
`/check` from a phone.

## Conventions

Money is a decimal amount plus a currency, never a float. Timestamps are stored in
UTC and converted only for display. The comdirect client, the Telegram sender and
the argument parser are boundary code; drift calculation takes positions and a
target allocation as plain values and needs no network to test.

The CLI follows the usual contract: the report on stdout, everything else on
stderr, zero on success and non-zero on failure. It refuses to start without a
terminal, and refuses before the login rather than after, because reaching the
bank at all spends one of the five TAN challenges.

The Telegram `/check` handler is registered with `block=False`. Without it the
update loop sits inside the running check and `/done` never arrives, which
deadlocks the bot on the one message it is waiting for.

## Commands

`./.claude/check.sh` runs ruff, ruff format, mypy strict and pytest. CI runs the
same script, and so does the commit gate, so a green run locally means a green run
everywhere. Run a single test file with `pytest tests/test_drift.py`.

Errors from the bank carry the bank's own message, not just a status code. A bare
"HTTP 400" is what made the first live failure take a web search to diagnose. The
one exception is the token endpoint, whose error bodies can quote the credentials
that were sent, so those failures stay bare on purpose.

Dependencies are pinned in `requirements.txt` and `requirements-dev.txt`, both
generated with `uv pip compile` from `pyproject.toml`. Regenerate them in the same
change that edits a dependency.
