from unittest.mock import MagicMock
from backend.search.reranker import rerank


def _hit(job_id: str, summary_text: str = "") -> dict:
    return {"_source": {"job_id": job_id, "summary_text": summary_text}}


def test_sorts_by_score_descending():
    reranker = MagicMock()
    reranker.predict.return_value = [0.2, 0.9, 0.5]
    result = rerank(reranker, [_hit("a"), _hit("b"), _hit("c")], "python")
    assert [h["_source"]["job_id"] for h in result] == ["b", "c", "a"]


def test_respects_top_k():
    reranker = MagicMock()
    reranker.predict.return_value = list(range(30))
    result = rerank(reranker, [_hit(str(i)) for i in range(30)], "x", top_k=20)
    assert len(result) == 20


def test_falls_back_to_empty_string_for_missing_summary():
    reranker = MagicMock()
    reranker.predict.return_value = [0.1]
    rerank(reranker, [{"_source": {"job_id": "a"}}], "x")
    pairs = reranker.predict.call_args[0][0]
    assert pairs[0][1] == ""


def test_builds_correct_pairs():
    reranker = MagicMock()
    reranker.predict.return_value = [0.5]
    rerank(reranker, [_hit("a", "ml engineer")], "python ml")
    assert reranker.predict.call_args[0][0] == [("python ml", "ml engineer")]
