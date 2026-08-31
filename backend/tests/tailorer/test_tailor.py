import pytest
from unittest.mock import MagicMock, patch


def _mock_groq_response(text: str):
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_parse_cover_letter_response():
    from backend.tailorer.tailor import _parse_cover_letter_response
    raw = "COMPANY: Stripe\nPOSITION: ML Engineer\n---\nDear Hiring Manager,\n\nTest letter.\n\nKind regards,\nJane"
    company, position, letter = _parse_cover_letter_response(raw)
    assert company == "Stripe"
    assert position == "ML Engineer"
    assert "Dear Hiring Manager" in letter


def test_build_cover_letter_docx_returns_bytes():
    from backend.tailorer.tailor import _build_docx_bytes
    data = _build_docx_bytes("Dear Hiring Manager,\n\nTest.\n\nKind regards,\nJane")
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_build_cv_docx_with_no_modifications():
    from backend.tailorer.tailor import _apply_cv_modifications
    import docx, io
    doc = docx.Document()
    doc.add_paragraph("Original text")
    buf = io.BytesIO()
    doc.save(buf)
    cv_bytes = buf.getvalue()
    result = _apply_cv_modifications(cv_bytes, [])
    assert isinstance(result, bytes)
    assert len(result) > 0
