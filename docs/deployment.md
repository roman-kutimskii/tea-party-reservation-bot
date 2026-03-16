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
cp deploy/compose/env/stage.env.example /opt/tea-party-reservation-bot/env/stage.env
cp deploy/compose/env/stage.secrets.env.example /opt/tea-party-reservation-bot/env/stage.secrets.env
cp deploy/compose/compose.yml /opt/tea-party-reservation-bot/compose/compose.yml
cp deploy/compose/compose.stage.yml /opt/tea-party-reservation-bot/compose/compose.stage.yml
cd /opt/tea-party-reservation-bot/compose
export APP_IMAGE=ghcr.io/your-org/tea-party-reservation-bot@sha256:replace-me
docker compose -f compose.yml -f compose.stage.yml up -d
```

Stage and prod now fail fast if these values are missing:

- `APP_IMAGE`
- `POSTGRES_PASSWORD`

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
- `TEA_PARTY_METRICS__ENABLED`
- `TEA_PARTY_METRICS__HOST`
- `TEA_PARTY_METRICS__BOT_PORT`
- `TEA_PARTY_METRICS__WORKER_PORT`

When metrics are enabled, the bot and worker metrics listeners also expose lightweight operational probes on the same port:

- `/metrics` for Prometheus scraping
- `/healthz` for process liveness
- `/readyz` for startup readiness

## CI/CD contract

The GitHub Actions workflows expect:

- `pyproject.toml` managed with `uv`
- Ruff, mypy, and pytest configured in the project
- Docker build succeeds from repository root
- unit and integration suites are runnable separately via `tests/unit` and `tests/integration`
- stage/prod SSH secrets and deployment paths configured in GitHub environments
- stage/prod `OPS_DEPLOY_WEBHOOK_URL` environment secrets configured when deployment notifications are required
- deployment env files already exist on the target host before CD runs

## Secrets handling

- keep `deploy/compose/env/*.env` on the server, not in git
- use GitHub environment secrets for GHCR, SSH keys, and deployment hosts
- keep Ansible secrets in vault-backed variables such as `vault_restic_password`
- do not leave `ufw_allowed_ssh_cidrs` open to `0.0.0.0/0` outside temporary break-glass access

## Backup expectations

- daily `pg_dump` via systemd timer
- restic copy to off-VPS object storage
- optional backup heartbeat ping via `backup_healthcheck_url`
- backup failures and runtime incidents can post to `monitoring_alert_webhook_url`
- monthly restore drill using `ops/runbooks/restore.md`

## Monitoring wiring

- `infra/ansible/roles/monitoring` now installs a systemd timer that checks bot and worker `/readyz` endpoints every five minutes and optionally pings an external uptime service
- the same probe inspects recent container logs for `error` and `critical` structured log entries and sends a single alert per active burst window
- deployment workflows can POST structured deployment events to `OPS_DEPLOY_WEBHOOK_URL`
