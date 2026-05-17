import numpy as np
from unittest.mock import MagicMock, patch
from ingestion.embedder import embed, _summary_text
from ingestion.offer.models import OfferSummary


def test_summary_text_joins_all_fields():
    s = OfferSummary(role_info=["senior engineer"], requirements=["Python"], responsibilities=["train models"], domain=["NLP"])
    result = _summary_text(s)
    assert "senior engineer" in result
    assert "Python" in result
    assert "train models" in result
    assert "NLP" in result


def test_embed_none_for_none_summary():
    assert embed("title", None) is None


def test_embed_none_for_empty_summary():
    assert embed("title", OfferSummary()) is None


def test_embed_returns_list_of_floats():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1] * 384)
    with patch("ingestion.embedder.get_embedder", return_value=mock_model):
        result = embed("ML Engineer", OfferSummary(role_info=["builds ML models"]))
    assert isinstance(result, list)
    assert len(result) == 384


def test_embed_includes_title_in_input():
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.0] * 384)
    with patch("ingestion.embedder.get_embedder", return_value=mock_model):
        embed("Data Scientist", OfferSummary(role_info=["NLP researcher"]))
    text_arg = mock_model.encode.call_args[0][0]
    assert text_arg.startswith("Data Scientist\n")
    assert "NLP researcher" in text_arg
