# syntax=docker/dockerfile:1.7
# Base images are pinned by digest; bump them deliberately.
FROM ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

FROM python:3.13-slim-trixie@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1 AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

# Development image: all dependency groups, sources mounted at runtime.
FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Production image: runtime dependencies only, unprivileged user.
FROM base AS runtime
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable \
 && useradd --create-home --uid 10001 esphea \
 && mkdir -p /data \
 && chown esphea:esphea /data
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV ESPHEA_DATA_DIR=/data
# The entrypoint starts as root only to adopt the data directory's owner, then drops
# privileges (see docker-entrypoint.sh).
ENTRYPOINT ["docker-entrypoint.sh"]
EXPOSE 8000
CMD ["uvicorn", "esphea.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
