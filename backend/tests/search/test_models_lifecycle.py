import pytest
from unittest.mock import patch, MagicMock
import backend.search.models_lifecycle as m
from backend.search.models_lifecycle import get_biencoder, get_reranker, init_models


def test_get_biencoder_raises_before_init():
    m._biencoder = None
    with pytest.raises(AssertionError):
        get_biencoder()


def test_get_reranker_raises_before_init():
    m._reranker = None
    with pytest.raises(AssertionError):
        get_reranker()


def test_init_models_sets_both():
    m._biencoder = None
    m._reranker = None
    mock_st = MagicMock()
    mock_ce = MagicMock()
    with patch("backend.search.models_lifecycle.SentenceTransformer", return_value=mock_st), \
         patch("backend.search.models_lifecycle.CrossEncoder", return_value=mock_ce):
        init_models()
    assert get_biencoder() is mock_st
    assert get_reranker() is mock_ce
