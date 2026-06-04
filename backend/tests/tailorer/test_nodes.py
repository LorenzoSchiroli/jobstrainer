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
        "nav_phase": "start",
        "nav_snapshot": None,
        "nav_action": None,
        "nav_history": [],
        "nav_memory": "",
    }
    return {**base, **overrides}


def test_make_state_has_new_fields():
    from backend.tailorer.state import TailorerState
    # Verify new fields exist in the TypedDict definition
    import typing
    hints = typing.get_type_hints(TailorerState)
    assert 'nav_memory' in hints
    assert 'last_snapshot' in hints


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


def test_decide_next_navigation_returns_batched_actions():
    """_decide_next_navigation returns a dict with current_state + action array."""
    import json
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({
        "current_state": {
            "evaluation_previous_goal": "Unknown - first step",
            "memory": "Starting navigation to Stripe careers page.",
            "next_goal": "Find apply button"
        },
        "action": [{"action": "click_element", "index": 1}]
    })

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        from backend.tailorer import nodes as nodes_module
        # Force reimport to get fresh module
        import importlib
        importlib.reload(nodes_module)
        result = nodes_module._decide_next_navigation(instance, {
            "url": "https://stripe.com/jobs/123",
            "title": "Software Engineer",
            "elements": "[1]<button >Apply Now />\n[2]<a href=/careers >Careers />",
            "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
        }, "Software Engineer", [], "")

    assert "current_state" in result
    assert "action" in result
    assert isinstance(result["action"], list)
    assert result["action"][0]["action"] == "click_element"


def test_navigate_to_apply_stores_nav_memory():
    """navigate_to_apply persists LLM memory into nav_memory state field."""
    import json
    import os
    import importlib
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({
        "current_state": {
            "evaluation_previous_goal": "Unknown",
            "memory": "On careers page, found apply button at index 1.",
            "next_goal": "Click apply"
        },
        "action": [{"action": "at_form"}]
    })

    from backend.tailorer import nodes as nodes_module
    importlib.reload(nodes_module)

    with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_MODEL_LARGE": "test-model"}), \
         patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM, \
         patch("backend.tailorer.nodes.interrupt") as mock_interrupt:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        mock_interrupt.return_value = {
            "url": "https://stripe.com/apply",
            "title": "Apply",
            "elements": "[2]<input type=text />",
            "scroll_y": 0, "scroll_height": 500, "viewport_height": 800
        }
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot={"url": "https://stripe.com/jobs/123", "elements": "[1]<button >Apply />", "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800},
            nav_memory="",
            nav_history=["https://stripe.com"],
        )
        result = nodes_module.navigate_to_apply(state)

    assert result["nav_memory"] == "On careers page, found apply button at index 1."
