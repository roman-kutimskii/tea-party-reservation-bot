# Rollback Runbook

1. Identify the previous known-good image digest from GHCR or deployment history.
2. Set `APP_IMAGE` back to that digest on the host.
3. Run `docker compose -f compose.yml -f compose.prod.yml pull`.
4. Redeploy with `docker compose -f compose.yml -f compose.prod.yml up -d --remove-orphans`.
5. Verify the bot reconnects, worker drains outbox, and registrations still open correctly.
6. If the failed release included an incompatible migration, stop and follow `ops/runbooks/restore.md` instead of forcing the older app onto the newer schema.

Notes:

- prefer backward-compatible migrations so app rollback remains image-only
- keep the failed containers until root cause is captured from logs
