from opensearchpy import AsyncOpenSearch
from backend.opensearch_client import INDEX_NAME, PIPELINE_NAME
from backend.search.filters import SearchFilters, build_filters


def build_hybrid_query(
    semantic_query: str,
    query_embedding: list[float],
    filters: SearchFilters,
    size: int = 50,
) -> dict:
    filter_clauses = build_filters(filters)
    return {
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "bool": {
                            "must": {"match": {"description": semantic_query}},
                            "filter": filter_clauses,
                        }
                    },
                    {
                        "bool": {
                            "must": {"knn": {"embedding": {"vector": query_embedding, "k": 100}}},
                            "filter": filter_clauses,
                        }
                    },
                ]
            }
        },
        "size": size,
    }


async def hybrid_retrieve(
    client: AsyncOpenSearch,
    query_embedding: list[float],
    filters: SearchFilters,
) -> list[dict]:
    query = build_hybrid_query(filters.semantic_query, query_embedding, filters)
    response = await client.search(
        index=INDEX_NAME,
        body=query,
        params={"search_pipeline": PIPELINE_NAME},
    )
    return response["hits"]["hits"]
