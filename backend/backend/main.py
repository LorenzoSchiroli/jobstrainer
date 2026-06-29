import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from sqlalchemy import select
from backend.routers import companies, jobs
from backend.routers.search import router as search_router
from backend.routers.auth import router as auth_router
from backend.routers.cv import router as cv_router
from backend.tailorer.router import router as tailorer_router
from backend.search.models_lifecycle import init_models
from backend.opensearch_client import init_opensearch, get_opensearch, INDEX_NAME
from backend.outbox.worker import outbox_worker
from backend.database import get_session_factory
from backend.models import Job

logger = logging.getLogger(__name__)

_checkpointer: AsyncPostgresSaver | None = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized")
    return _checkpointer


async def _backfill_created_at() -> None:
    factory = get_session_factory()
    os_client = get_opensearch()
    async with factory() as session:
        rows = (await session.execute(select(Job.id, Job.created_at))).all()
    if not rows:
        return
    body = []
    for job_id, created_at in rows:
        body.append({"update": {"_id": str(job_id)}})
        body.append({"doc": {"created_at": created_at.isoformat()}, "doc_as_upsert": False})
    await os_client.bulk(index=INDEX_NAME, body=body)
    logger.info("Backfilled created_at for %d jobs in OpenSearch", len(rows))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _checkpointer
    init_models()
    await init_opensearch()
    await _backfill_created_at()

    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        await checkpointer.setup()
        _checkpointer = checkpointer

        task = asyncio.create_task(outbox_worker())
        yield
        task.cancel()


app = FastAPI(title="jobstrainer backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    # The Tailorer side panel (chrome-extension:// origin) calls /auth/me and other
    # endpoints directly; a concrete regex (not "*") is allowed alongside credentials.
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(search_router)
app.include_router(auth_router)
app.include_router(cv_router)
app.include_router(tailorer_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
