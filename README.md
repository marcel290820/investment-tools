# investment-tools

Personal tooling for managing investments.

## Status

Early. First tool in progress: a read-only portfolio tracker that watches asset
allocation drift and sends a Telegram alert when the real allocation moves too
far from the target.

## Secrets

This repository is public. No credential, token, or account identifier ever
goes into a tracked file. Everything sensitive is read from the environment;
see `.env.example` for the variable names.
