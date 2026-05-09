FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/pyproject.toml

RUN uv sync --package backend --no-dev

COPY backend/ ./backend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
