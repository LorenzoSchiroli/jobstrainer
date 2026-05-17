from sentence_transformers.cross_encoder import CrossEncoder


def rerank(
    reranker: CrossEncoder,
    hits: list[dict],
    semantic_query: str,
    top_k: int = 20,
) -> list[dict]:
    pairs = [(semantic_query, hit["_source"].get("summary_text") or "") for hit in hits]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(hits, scores), key=lambda x: x[1], reverse=True)
    return [hit for hit, _ in ranked[:top_k]]
