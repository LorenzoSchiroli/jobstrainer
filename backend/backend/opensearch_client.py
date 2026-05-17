import os
from opensearchpy import AsyncOpenSearch

_client: AsyncOpenSearch | None = None

INDEX_NAME = "jobs"
PIPELINE_NAME = "hybrid-pipeline"

_INDEX_BODY = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "job_id":                   {"type": "keyword"},
            "company_id":               {"type": "keyword"},
            "title":                    {"type": "text"},
            "description":              {"type": "text"},
            "summary_text":             {"type": "text"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 384,
                "method": {"name": "hnsw", "space_type": "cosine", "engine": "faiss"},
            },
            "employment_type":          {"type": "keyword"},
            "location_type":            {"type": "keyword"},
            "seniority":                {"type": "keyword"},
            "languages_required":       {"type": "keyword"},
            "is_consulting":            {"type": "boolean"},
            "is_startup":               {"type": "boolean"},
            "industry":                 {"type": "keyword"},
            "country":                  {"type": "keyword"},
            "review_score":             {"type": "float"},
            "financial_health_score":   {"type": "integer"},
        }
    },
}

_PIPELINE_BODY = {
    "description": "Hybrid BM25 + kNN normalization",
    "phase_results_processors": [{
        "normalization-processor": {
            "normalization": {"technique": "min_max"},
            "combination": {
                "technique": "arithmetic_mean",
                "parameters": {"weights": [0.5, 0.5]},
            },
        }
    }],
}


def get_opensearch() -> AsyncOpenSearch:
    assert _client is not None, "OpenSearch client not initialized"
    return _client


async def init_opensearch() -> None:
    global _client
    url = os.environ["OPENSEARCH_URL"]
    _client = AsyncOpenSearch(hosts=[url])
    if not await _client.indices.exists(index=INDEX_NAME):
        await _client.indices.create(index=INDEX_NAME, body=_INDEX_BODY)
    await _client.transport.perform_request(
        method="PUT",
        url=f"/_search/pipeline/{PIPELINE_NAME}",
        body=_PIPELINE_BODY,
    )
