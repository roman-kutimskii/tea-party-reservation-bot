#!/bin/sh
set -eu

if [ "${APP_MIGRATE_ON_START:-0}" = "1" ]; then
    if [ -n "${MIGRATION_COMMAND:-}" ]; then
        /bin/sh -c "${MIGRATION_COMMAND}"
    else
        printf '%s\n' 'APP_MIGRATE_ON_START=1 but MIGRATION_COMMAND is empty.' >&2
        exit 1
    fi
fi

exec "$@"
