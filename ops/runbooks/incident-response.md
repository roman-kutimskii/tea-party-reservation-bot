# Incident Response Basics

Severity guide:

- `sev1`: bot unavailable, booking corruption risk, or suspected overbooking
- `sev2`: publish failures, backup failures, or partial notification outage
- `sev3`: degraded admin ergonomics without booking correctness risk

First 15 minutes:

1. Acknowledge the incident and assign an incident lead.
2. Freeze risky admin actions such as batch publication or manual participant moves.
3. Capture `docker compose ps`, recent logs, host disk usage, and PostgreSQL health.
4. Check whether the issue is app-only, Telegram API-related, or host-wide.
5. If booking correctness is uncertain, stop `bot` and `worker` before making manual DB changes.

Key checks:

- `docker compose logs --since=15m bot worker`
- `docker stats --no-stream`
- `df -h`
- `journalctl -u tea-party-compose.service -n 200`
- `systemctl status tea-party-backup.timer`

Escalate immediately when:

- there is evidence of double booking or duplicate active reservations
- backups are missing and the database host is unstable
- Telegram bot token may be leaked
