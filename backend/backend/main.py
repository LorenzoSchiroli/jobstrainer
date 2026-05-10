from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend.routers import companies, jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="jobstrainer backend", lifespan=lifespan)
app.include_router(companies.router)
app.include_router(jobs.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
