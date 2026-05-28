import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_state(**overrides):
    base = {
        "job_id": "abc",
        "user_id": "user1",
        "job_title": "ML Engineer",
        "job_description": "Build ML systems",
        "company_homepage": "https://stripe.com",
        "profile": {"first_name": "Lorenzo", "email": "l@test.com"},
        "cv_text": "Lorenzo Schiroli, ML Engineer",
        "apply_url": "",
        "current_page": 0,
        "filled_fields": {},
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "pending_correction": None,
        "retry_count": 0,
        "status": "navigating",
    }
    return {**base, **overrides}


def test_find_best_link_returns_url():
    from backend.tailorer.nodes import _find_best_link_in_snapshot
    snapshot = {
        "links": [
            {"label": "Careers", "href": "https://stripe.com/jobs"},
            {"label": "About", "href": "https://stripe.com/about"},
        ]
    }
    result = _find_best_link_in_snapshot(snapshot, ["careers", "jobs"])
    assert result == "https://stripe.com/jobs"


def test_find_best_link_returns_none_when_no_match():
    from backend.tailorer.nodes import _find_best_link_in_snapshot
    snapshot = {"links": [{"label": "About", "href": "https://stripe.com/about"}]}
    result = _find_best_link_in_snapshot(snapshot, ["careers", "jobs"])
    assert result is None


def test_build_fill_commands_maps_profile_fields():
    import json
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"field_id": "first_name", "value": "Lorenzo", "uncertain": False}
    ])

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        from backend.tailorer.nodes import _map_fields_sync
        state = _make_state()
        snapshot = {"fields": [{"id": "first_name", "label": "First Name", "type": "text", "value": ""}]}
        cmds = _map_fields_sync(instance, snapshot, state)
    assert cmds[0]["field_id"] == "first_name"
    assert cmds[0]["value"] == "Lorenzo"
