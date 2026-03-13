# Deploy Runbook

1. Verify the target image digest in GHCR and confirm stage smoke checks passed.
2. SSH to the host as `deploy` and confirm env files exist in `/opt/tea-party-reservation-bot/env`.
3. Update `APP_IMAGE` in the active env file or let GitHub Actions export it for the session.
4. Run `docker compose -f compose.yml -f compose.prod.yml pull` from `/opt/tea-party-reservation-bot/compose`.
5. Run migrations with `docker compose -f compose.yml -f compose.prod.yml run --rm -e APP_MIGRATE_ON_START=1 bot true`.
6. Start services with `docker compose -f compose.yml -f compose.prod.yml up -d --remove-orphans`.
7. Verify `docker compose ... ps`, inspect logs for `bot` and `worker`, and execute the Telegram smoke flow from the specification.

Failure gates:

- stop if migrations fail
- stop if `postgres` is unhealthy
- stop if bot long polling does not connect or Telegram posting rights are missing
