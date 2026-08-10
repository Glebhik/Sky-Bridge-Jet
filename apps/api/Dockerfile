FROM python:3.14-slim@sha256:a7fb1e634c4a578f9e0bd6327f11a3cde11b7a9395f48e24360c0988bcc5c2bc

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev

COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "sky_bridge_jet.main:app", "--host", "0.0.0.0", "--port", "8000"]
