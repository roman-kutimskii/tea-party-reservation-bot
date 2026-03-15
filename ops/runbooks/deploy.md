# Deploy Runbook

1. Verify the target image digest in GHCR and confirm stage smoke checks passed.
2. SSH to the host as `deploy` and confirm env files exist in `/opt/tea-party-reservation-bot/env`.
3. From `/opt/tea-party-reservation-bot/compose`, export the exact immutable image reference for the session: `export APP_IMAGE=ghcr.io/<org>/<repo>@sha256:<digest>`.
4. Confirm required secrets are present before deployment: `POSTGRES_PASSWORD`, `TEA_PARTY_TELEGRAM__BOT_TOKEN`, and any GHCR read credentials.
5. Run `docker compose -f compose.yml -f compose.prod.yml pull`.
6. Run migrations with `docker compose -f compose.yml -f compose.prod.yml run --rm -e APP_MIGRATE_ON_START=1 bot true`.
7. Start services with `docker compose -f compose.yml -f compose.prod.yml up -d --remove-orphans`.
8. Verify `docker compose ... ps`, inspect logs for `bot` and `worker`, and execute the Telegram smoke flow from the specification.

Failure gates:

- stop if migrations fail
- stop if `postgres` is unhealthy
- stop if `APP_IMAGE` is missing or points to a mutable tag that was not explicitly approved
- stop if bot long polling does not connect or Telegram posting rights are missing
