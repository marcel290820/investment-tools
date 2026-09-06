# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Personal tooling for managing investments. One tool exists per concern; they share
this repo but not a framework.

**Planned first tool: allocation drift tracker.** Reads the owner's comdirect depot
read-only, compares the real asset allocation against a target allocation, and
sends a Telegram message when a position drifts past its tolerance band. No code
is written yet, so the sections below are decisions and constraints, not a
description of what is on disk.

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

So an unattended daily timer cannot authenticate on its own. Only two shapes work:

1. A resident process that logs in once with a manual TAN and refreshes every few
   minutes to hold the session open. Any restart or network gap ends the session and
   needs a new TAN.
2. A Telegram command that starts a login on demand. The owner approves the TAN, the
   tool pulls positions, reports drift, and lets the session die.

Shape 2 fits a drift check, which is a weekly-or-slower question. Prefer it, and have
the tool ask for a TAN over Telegram rather than failing silently when a session is
gone.

Read-only means read-only. The API exposes order placement under `/brokerage/v3/orders`.
Nothing in this repo calls it.

## Deployment

Hetzner VPS, Ubuntu 24.04, x86_64, 7.6 GB RAM. Reached over the `hetzner` ssh alias.
No Docker installed, and none is wanted for a job this small.

Copy the pattern already running there at `/opt/daily-digest`, which does the same
job shape (scheduled Python, Telegram output):

- code in `/opt/<tool>`, owned by a dedicated unprivileged user, running from a venv
- a `oneshot` systemd service plus a timer with `OnCalendar` in `Europe/Berlin` and
  `Persistent=true`
- secrets in `/etc/<tool>/env`, root-owned and mode 600, pulled in with
  `EnvironmentFile`, never in the unit file and never in the repo
- hardening flags on the unit: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`, `PrivateDevices`
- writable state via `StateDirectory`, which lands in `/var/lib/<tool>`

Read `systemctl cat daily-digest@.service` on the VPS before writing a new unit.

## Conventions

Money is a decimal amount plus a currency, never a float. Timestamps are stored in
UTC and converted only for display in the Telegram message. The comdirect client and
the Telegram sender are boundary code; drift calculation takes positions and a target
allocation as plain values and needs no network to test.

## Commands

No build or test tooling exists yet. When it lands, add `.claude/check.sh` running
lint, typecheck, and tests in one command; the commit hook and CI both call it.
