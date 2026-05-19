FROM python:3.13

WORKDIR /app

RUN pip install uv --quiet

COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/pyproject.toml

RUN uv sync --package backend --no-dev

RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
RUN uv run python -c "from sentence_transformers.cross_encoder import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY backend/ ./backend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
