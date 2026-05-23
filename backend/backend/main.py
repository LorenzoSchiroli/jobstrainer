import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from backend.routers import companies, jobs
from backend.routers.search import router as search_router
from backend.routers.auth import router as auth_router
from backend.routers.cv import router as cv_router
from backend.search.models_lifecycle import init_models
from backend.opensearch_client import init_opensearch
from backend.outbox.worker import outbox_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_models()
    await init_opensearch()
    task = asyncio.create_task(outbox_worker())
    yield
    task.cancel()


app = FastAPI(title="jobstrainer backend", lifespan=lifespan)
app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(search_router)
app.include_router(auth_router)
app.include_router(cv_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
