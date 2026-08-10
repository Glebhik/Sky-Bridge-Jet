FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "sky_bridge_jet.main:app", "--host", "0.0.0.0", "--port", "8000"]
