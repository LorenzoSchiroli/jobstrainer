from retriever.filters import is_english


def test_english_title_passes():
    assert is_english("Machine Learning Engineer") is True


def test_german_title_fails():
    assert is_english("Softwareentwickler für maschinelles Lernen") is False


def test_french_title_fails():
    assert is_english("Ingénieur en apprentissage automatique") is False


def test_empty_string_passes():
    assert is_english("") is True


def test_mixed_mostly_ascii_passes():
    assert is_english("Senior Engineer — Berlin") is True
