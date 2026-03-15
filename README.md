# tea-party-reservation-bot

Telegram-бот для бронирования места на чаепитии.

## Project layout

- `src/tea_party_reservation_bot`: application code
- `tests/unit`: fast unit coverage
- `tests/integration`: database-backed integration coverage
- `deploy/compose`: local, stage, and prod Compose overlays
- `.github/workflows`: CI and deployment workflows
- `infra/terraform`: VPS and firewall provisioning
- `infra/ansible`: host bootstrap and operational roles
- `ops/runbooks`: deploy, rollback, restore, and incident procedures
- `docs/deployment.md`: deployment contract and environment wiring

## Local development

```bash
uv sync --frozen --all-extras --dev
uv run pytest tests/unit -q
uv run pytest tests/integration -q
```

Local Docker startup:

```bash
cp deploy/compose/env/local.env.example deploy/compose/env/local.env
cp deploy/compose/env/postgres.env.example deploy/compose/env/postgres.env
docker compose -f deploy/compose/compose.yml -f deploy/compose/compose.local.yml up --build
```

## Deployment notes

- stage and prod require `APP_IMAGE` plus secret env files on the server
- `deploy/compose/compose.yml` now fails fast if `APP_IMAGE` or `POSTGRES_PASSWORD` is missing
- Ansible inventory must provide vault-backed secret variables instead of plaintext placeholders
- GitHub Actions deploys are serialized per environment to avoid overlapping releases

See `docs/deployment.md` and `ops/runbooks/deploy.md` for the operational flow.
