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


def test_map_fields_sync_returns_index_based_commands():
    """_map_fields_sync returns commands with index (int) not field_id (str)."""
    import json
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 2, "value": "Lorenzo", "action": "input_text", "uncertain": False},
        {"index": 7, "value": "__CV__", "action": "file_upload", "uncertain": False},
        {"index": 9, "value": "???", "action": "input_text", "uncertain": True},
    ])

    with patch("backend.tailorer.nodes.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        import importlib
        from backend.tailorer import nodes as nodes_module
        importlib.reload(nodes_module)
        state = _make_state()
        snapshot = {
            "url": "https://greenhouse.io/apply",
            "elements": "[2]<input type=text placeholder='First name' />\n[7]<input type=file />\n[9]<input type=text placeholder='Work auth' />",
            "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
        }
        cmds = nodes_module._map_fields_sync(instance, snapshot, state)

    assert cmds[0]["index"] == 2
    assert cmds[0]["action"] == "input_text"
    assert cmds[1]["value"] == "__CV__"
    assert cmds[2]["uncertain"] is True
    assert "field_id" not in cmds[0]


def test_fill_page_confirm_shows_only_uncertain_and_files():
    """fill_page interrupt shows only uncertain fields and file upload commands."""
    import json
    import os
    import importlib
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 2, "value": "Lorenzo", "action": "input_text", "uncertain": False},
        {"index": 7, "value": "__CV__", "action": "file_upload", "uncertain": False},
        {"index": 9, "value": "???", "action": "input_text", "uncertain": True},
    ])

    from backend.tailorer import nodes as nodes_module
    importlib.reload(nodes_module)

    with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_MODEL_LARGE": "test-model"}), \
         patch.object(nodes_module, "ChatOpenAI") as MockLLM, \
         patch.object(nodes_module, "interrupt") as mock_interrupt:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        mock_interrupt.return_value = {"type": "user_approved"}
        state = _make_state(
            last_snapshot={
                "url": "https://greenhouse.io/apply",
                "elements": "[2]<input type=text />\n[7]<input type=file />\n[9]<input type=text />",
                "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
            },
            filled_fields={},
        )
        nodes_module.fill_page(state)

    interrupt_call = mock_interrupt.call_args[0][0]
    assert interrupt_call["type"] == "fill_and_confirm"
    # confirm_commands shows only uncertain + file (not index 2)
    confirm_cmds = interrupt_call["confirm_commands"]
    shown_indices = {c["index"] for c in confirm_cmds}
    assert 2 not in shown_indices   # certain text field — NOT shown
    assert 7 in shown_indices       # file upload — shown
    assert 9 in shown_indices       # uncertain — shown


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
