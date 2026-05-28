import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel
from groq import Groq

from backend.database import get_session
from backend.models import Job, User
from backend.schemas import JobSearchResponse
from backend.search.filters import SearchFilters
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import extract_filters, get_groq_client
from backend.search.retrieval import hybrid_retrieve
from backend.search.reranker import rerank
from backend.opensearch_client import get_opensearch
from backend.auth.dependencies import get_current_user
from backend.tailorer.models import ApplicantProfile

router = APIRouter(prefix="/jobs", tags=["search"])
logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str


@router.post("/search", response_model=list[JobSearchResponse])
async def search_jobs(
    body: SearchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    groq_client: Groq = Depends(get_groq_client),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
) -> list[JobSearchResponse]:
    profile_result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.cv_text:
        raise HTTPException(status_code=400, detail="No CV uploaded. Please upload your CV first.")

    t0 = time.perf_counter()

    filters: SearchFilters = await extract_filters(groq_client, profile.cv_text, body.query)
    t1 = time.perf_counter()

    query_embedding: list[float] = biencoder.encode(filters.semantic_query).tolist()
    t2 = time.perf_counter()

    hits = await hybrid_retrieve(os_client, query_embedding, filters)
    t3 = time.perf_counter()

    ranked_hits = rerank(reranker, hits, filters.semantic_query)
    t4 = time.perf_counter()

    if not ranked_hits:
        logger.info("[search timing] query_understanding=%.3fs embed=%.3fs retrieve=%.3fs rerank=%.3fs total=%.3fs (no hits)", t1-t0, t2-t1, t3-t2, t4-t3, t4-t0)
        return []

    ranked_ids = [hit["_source"]["job_id"] for hit in ranked_hits]
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id.in_(ranked_ids))
    )
    t5 = time.perf_counter()

    logger.info("[search timing] query_understanding=%.3fs embed=%.3fs retrieve=%.3fs rerank=%.3fs db=%.3fs total=%.3fs", t1-t0, t2-t1, t3-t2, t4-t3, t5-t4, t5-t0)

    jobs_by_id = {str(job.id): job for job in result.scalars()}
    return [jobs_by_id[id_] for id_ in ranked_ids if id_ in jobs_by_id]
