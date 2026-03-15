# Restore Runbook

1. Put the bot into maintenance mode operationally: stop new announcements and warn admins not to publish new events.
2. Confirm the latest restic snapshot and matching `pg_dump` artifact exist.
3. Stop app containers with `docker compose -f compose.yml -f compose.prod.yml stop bot worker` and record the current `APP_IMAGE` digest before changing anything.
4. Restore PostgreSQL into a clean database or replacement host:
   - fetch the chosen dump from restic
   - run `pg_restore --clean --if-exists --no-owner --dbname <target_db> <dump_file>`
5. Run schema validation checks and inspect critical tables: `event_occurrences`, `reservations`, `waitlist_entries`, `outbox_events`.
6. Start `postgres`, then `worker`, then `bot`, keeping `APP_IMAGE` pinned to the intended recovery version.
7. Reconcile pending outbox events before reopening admin publishing.
8. Record the incident timeline, backup timestamp, and any data-loss window.

Minimum monthly drill:

- restore to staging
- verify login, event list, registration, cancellation, and waitlist promotion
