from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder

_biencoder: SentenceTransformer | None = None
_reranker: CrossEncoder | None = None


def init_models() -> None:
    global _biencoder, _reranker
    _biencoder = SentenceTransformer("BAAI/bge-small-en-v1.5")
    _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


def get_biencoder() -> SentenceTransformer:
    assert _biencoder is not None, "models not initialized"
    return _biencoder


def get_reranker() -> CrossEncoder:
    assert _reranker is not None, "models not initialized"
    return _reranker
