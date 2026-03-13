# Deployment Guide

This repository now includes a production-oriented delivery skeleton for the plain-VPS, long-polling MVP in `docs/specification-v1.0.md`.

## Runtime shape

- `bot`: Telegram long-polling process
- `worker`: outbox and scheduled jobs process
- `postgres`: primary transactional database
- optional reverse proxy is intentionally omitted for MVP because long polling does not require inbound webhook traffic

## Compose files

- `deploy/compose/compose.yml`: shared service definition
- `deploy/compose/compose.local.yml`: local build and local PostgreSQL port publishing
- `deploy/compose/compose.stage.yml`: stage env-file wiring and remote image pull
- `deploy/compose/compose.prod.yml`: prod env-file wiring and remote image pull

Example local startup:

```bash
cp deploy/compose/env/local.env.example deploy/compose/env/local.env
cp deploy/compose/env/postgres.env.example deploy/compose/env/postgres.env
docker compose -f deploy/compose/compose.yml -f deploy/compose/compose.local.yml up --build
```

Example stage startup on host:

```bash
cp deploy/compose/env/stage.env.example deploy/compose/env/stage.env
cp deploy/compose/env/stage.secrets.env.example deploy/compose/env/stage.secrets.env
docker compose -f compose.yml -f compose.stage.yml up -d
```

## Required application hooks

The delivery assets assume the future Python app exposes these commands or equivalents:

- bot process: `python -m tea_party_reservation_bot bot`
- worker process: `python -m tea_party_reservation_bot worker`
- migrations: `alembic upgrade head`

If the actual module paths differ, only the env values must change:

- `BOT_APP_COMMAND`
- `WORKER_APP_COMMAND`
- `MIGRATION_COMMAND`

Application settings use nested env vars with the `TEA_PARTY_` prefix, for example:

- `TEA_PARTY_APP__ENV`
- `TEA_PARTY_DATABASE__DSN`
- `TEA_PARTY_TELEGRAM__BOT_TOKEN`
- `TEA_PARTY_TELEGRAM__GROUP_CHAT_ID`
- `TEA_PARTY_WORKER__OUTBOX_POLL_INTERVAL_SECONDS`

## CI/CD contract

The GitHub Actions workflows expect:

- `pyproject.toml` managed with `uv`
- Ruff, mypy, and pytest configured in the project
- Docker build succeeds from repository root
- stage/prod SSH secrets and deployment paths configured in GitHub environments

## Secrets handling

- keep `deploy/compose/env/*.env` on the server, not in git
- keep Terraform provider tokens in shell environment or secret manager
- use GitHub environment secrets for GHCR, SSH keys, and deployment hosts

## Backup expectations

- daily `pg_dump` via systemd timer
- restic copy to off-VPS object storage
- Hetzner server backups enabled at infrastructure layer
- monthly restore drill using `ops/runbooks/restore.md`
