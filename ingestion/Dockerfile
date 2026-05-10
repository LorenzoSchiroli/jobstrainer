FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY ingestion/pyproject.toml ./ingestion/pyproject.toml

RUN uv sync --package ingestion --no-dev

RUN uv run playwright install --with-deps chromium

COPY ingestion/ ./ingestion/

WORKDIR /app/ingestion

CMD ["sh", "-c", "while true; do uv run python -m ingestion.offer \"$OFFER_QUERY\" --hours 2 --json; sleep 7200; done"]
