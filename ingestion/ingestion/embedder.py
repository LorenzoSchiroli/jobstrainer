import logging
from sentence_transformers import SentenceTransformer
from ingestion.offer.models import OfferSummary

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model (BAAI/bge-small-en-v1.5)...")
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        logger.info("Embedding model ready.")
    return _model


def _summary_text(summary: OfferSummary) -> str:
    parts = summary.role_info + summary.requirements + summary.responsibilities + summary.domain
    return " ".join(parts)


def embed(title: str, summary: OfferSummary | None) -> list[float] | None:
    if not summary:
        return None
    text = _summary_text(summary)
    if not text.strip():
        return None
    return get_embedder().encode(f"{title}\n{text}").tolist()
