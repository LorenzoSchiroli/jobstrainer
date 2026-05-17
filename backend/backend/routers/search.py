from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel
from groq import Groq

from backend.database import get_session
from backend.models import Job
from backend.schemas import JobSearchResponse
from backend.search.filters import SearchFilters
from backend.search.models_lifecycle import get_biencoder, get_reranker
from backend.search.query_understanding import extract_filters, get_groq_client
from backend.search.retrieval import hybrid_retrieve
from backend.search.reranker import rerank
from backend.opensearch_client import get_opensearch

router = APIRouter(prefix="/jobs", tags=["search"])


class SearchRequest(BaseModel):
    cv_text: str
    query: str


@router.post("/search", response_model=list[JobSearchResponse])
async def search_jobs(
    body: SearchRequest,
    session: AsyncSession = Depends(get_session),
    biencoder: SentenceTransformer = Depends(get_biencoder),
    reranker: CrossEncoder = Depends(get_reranker),
    groq_client: Groq = Depends(get_groq_client),
    os_client: AsyncOpenSearch = Depends(get_opensearch),
) -> list[JobSearchResponse]:
    filters: SearchFilters = await extract_filters(groq_client, body.cv_text, body.query)
    query_embedding: list[float] = biencoder.encode(filters.semantic_query).tolist()
    hits = await hybrid_retrieve(os_client, query_embedding, filters)
    ranked_hits = rerank(reranker, hits, filters.semantic_query)

    if not ranked_hits:
        return []

    ranked_ids = [hit["_source"]["job_id"] for hit in ranked_hits]
    result = await session.execute(
        select(Job).options(selectinload(Job.company)).where(Job.id.in_(ranked_ids))
    )
    jobs_by_id = {str(job.id): job for job in result.scalars()}
    return [jobs_by_id[id_] for id_ in ranked_ids if id_ in jobs_by_id]
