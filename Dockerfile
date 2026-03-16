# syntax=docker/dockerfile:1.7

FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /uvx /usr/local/bin/

RUN python -m venv /opt/venv

COPY . /app

RUN if [ -f pyproject.toml ]; then \
        uv sync --frozen --no-dev; \
    else \
        printf '%s\n' 'pyproject.toml is not present yet; runtime image built without app dependencies.'; \
    fi

RUN chmod +x /app/docker/entrypoint.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "tea_party_reservation_bot", "bot"]
