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
        "no_progress_count": 0,
    }
    return {**base, **overrides}


def test_make_state_has_new_fields():
    from backend.tailorer.state import TailorerState
    import typing
    hints = typing.get_type_hints(TailorerState)
    assert 'nav_memory' in hints
    assert 'last_snapshot' in hints
    assert 'no_progress_count' in hints


def test_decide_next_navigation_returns_batched_actions():
    import json
    import importlib
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({
        "current_state": {
            "evaluation_previous_goal": "Unknown - first step",
            "memory": "Starting navigation to Stripe careers page.",
            "next_goal": "Find apply button",
        },
        "action": [{"action": "click_element", "index": 1}],
    })

    from backend.tailorer import navigation as nav_module
    importlib.reload(nav_module)

    instance = MagicMock()
    instance.invoke.return_value = mock_resp
    result = nav_module._decide_next_navigation(
        instance,
        {
            "url": "https://stripe.com/jobs/123",
            "title": "Software Engineer",
            "elements": "[1]<button >Apply Now />\n[2]<a href=/careers >Careers />",
            "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
        },
        "Software Engineer", [], "",
    )

    assert "current_state" in result
    assert "action" in result
    assert isinstance(result["action"], list)
    assert result["action"][0]["action"] == "click_element"


def test_map_fields_returns_index_based_commands():
    import json
    import importlib
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 2, "value": "Lorenzo", "action": "input_text", "uncertain": False},
        {"index": 7, "value": "__CV__", "action": "file_upload", "uncertain": False},
        {"index": 9, "value": "???", "action": "input_text", "uncertain": True},
    ])

    from backend.tailorer import form as form_module
    importlib.reload(form_module)

    instance = MagicMock()
    instance.invoke.return_value = mock_resp
    state = _make_state()
    snapshot = {
        "url": "https://greenhouse.io/apply",
        "elements": "[2]<input type=text placeholder='First name' />\n[7]<input type=file />\n[9]<input type=text placeholder='Work auth' />",
        "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
    }
    cmds = form_module._map_fields(instance, snapshot, state)

    assert cmds[0]["index"] == 2
    assert cmds[0]["action"] == "input_text"
    assert cmds[1]["value"] == "__CV__"
    assert cmds[2]["uncertain"] is True
    assert "field_id" not in cmds[0]


def test_fill_page_confirm_shows_only_uncertain_and_files():
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

    from backend.tailorer import form as form_module
    importlib.reload(form_module)

    with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_MODEL_LARGE": "test-model"}), \
         patch("backend.tailorer.llm.ChatOpenAI") as MockLLM, \
         patch.object(form_module, "interrupt") as mock_interrupt:
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
        form_module.fill_page(state)

    interrupt_call = mock_interrupt.call_args[0][0]
    assert interrupt_call["type"] == "fill_and_confirm"
    confirm_cmds = interrupt_call["confirm_commands"]
    shown_indices = {c["index"] for c in confirm_cmds}
    assert 2 not in shown_indices
    assert 7 in shown_indices
    assert 9 in shown_indices


def test_navigate_to_apply_stores_nav_memory():
    import json
    import os
    import importlib
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = json.dumps({
        "current_state": {
            "evaluation_previous_goal": "Unknown",
            "memory": "On careers page, found apply button at index 1.",
            "next_goal": "Click apply",
        },
        "action": [{"action": "at_form"}],
    })

    from backend.tailorer import navigation as nav_module
    importlib.reload(nav_module)

    with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_MODEL_LARGE": "test-model"}), \
         patch("backend.tailorer.llm.ChatOpenAI") as MockLLM, \
         patch.object(nav_module, "interrupt") as mock_interrupt:
        instance = MockLLM.return_value
        instance.invoke.return_value = mock_resp
        mock_interrupt.return_value = {
            "url": "https://stripe.com/apply", "title": "Apply",
            "elements": "[2]<input type=text />",
            "scroll_y": 0, "scroll_height": 500, "viewport_height": 800,
        }
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot={
                "url": "https://stripe.com/jobs/123",
                "elements": "[1]<button >Apply />",
                "scroll_y": 0, "scroll_height": 1000, "viewport_height": 800,
            },
            nav_memory="",
            nav_history=["https://stripe.com"],
        )
        result = nav_module.navigate_to_apply(state)

    assert result["nav_memory"] == "On careers page, found apply button at index 1."


# ── Signal-based loop handling (no_progress_count) ───────────────────────────

import os as _os
import importlib as _importlib
from unittest.mock import patch as _patch, MagicMock as _MagicMock


def _reload_nav():
    from backend.tailorer import navigation as nav_module
    _importlib.reload(nav_module)
    return nav_module


_SAME_SNAP = {
    "url": "https://ea.com/careers/locations",
    "title": "Locations",
    "elements": "[10]<button >Explore opportunities />",
    "scroll_y": 0, "scroll_height": 6000, "viewport_height": 800,
}


def test_executing_increments_no_progress_when_snapshot_unchanged():
    nav_module = _reload_nav()
    with _patch.dict(_os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         _patch("backend.tailorer.llm.ChatOpenAI"), \
         _patch.object(nav_module, "interrupt") as mock_interrupt:
        mock_interrupt.return_value = dict(_SAME_SNAP)
        state = _make_state(
            nav_phase="executing",
            nav_snapshot=dict(_SAME_SNAP),
            nav_action={"current_state": {}, "action": [{"action": "click_element", "index": 10}]},
            no_progress_count=0,
        )
        result = nav_module.navigate_to_apply(state)
    assert result["no_progress_count"] == 1


def test_executing_resets_no_progress_when_page_changes():
    nav_module = _reload_nav()
    with _patch.dict(_os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         _patch("backend.tailorer.llm.ChatOpenAI"), \
         _patch.object(nav_module, "interrupt") as mock_interrupt:
        mock_interrupt.return_value = {
            "url": "https://ea.com/careers/jobs", "title": "Jobs",
            "elements": "[1]<a >ML Engineer />",
            "scroll_y": 0, "scroll_height": 3000, "viewport_height": 800,
        }
        state = _make_state(
            nav_phase="executing",
            nav_snapshot=dict(_SAME_SNAP),
            nav_action={"current_state": {}, "action": [{"action": "click_element", "index": 10}]},
            no_progress_count=2,
        )
        result = nav_module.navigate_to_apply(state)
    assert result["no_progress_count"] == 0


def test_deciding_does_not_trip_on_url_repeat_alone():
    nav_module = _reload_nav()
    decision = {"current_state": {"memory": "trying"}, "action": [{"action": "scroll_to_bottom"}]}
    with _patch.dict(_os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         _patch("backend.tailorer.llm.ChatOpenAI"), \
         _patch.object(nav_module, "_decide_next_navigation", return_value=decision) as mock_decide:
        url = "https://ea.com/careers/locations"
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot=dict(_SAME_SNAP),
            nav_history=[url, url],
            no_progress_count=0,
        )
        result = nav_module.navigate_to_apply(state)
    mock_decide.assert_called_once()
    assert result["nav_action"]["action"][0]["action"] == "scroll_to_bottom"


def test_deciding_passes_stuck_hint_at_nudge_threshold():
    nav_module = _reload_nav()
    decision = {"current_state": {"memory": "m"}, "action": [{"action": "go_to_url", "url": "https://ea.com/jobs"}]}
    with _patch.dict(_os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         _patch("backend.tailorer.llm.ChatOpenAI"), \
         _patch.object(nav_module, "_decide_next_navigation", return_value=decision) as mock_decide:
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot=dict(_SAME_SNAP),
            no_progress_count=nav_module._STUCK_NUDGE_THRESHOLD,
        )
        nav_module.navigate_to_apply(state)
    hint = mock_decide.call_args.kwargs.get("stuck_hint", "")
    assert hint


def test_deciding_escalates_to_user_at_user_threshold():
    nav_module = _reload_nav()
    with _patch.dict(_os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         _patch("backend.tailorer.llm.ChatOpenAI"), \
         _patch.object(nav_module, "_decide_next_navigation") as mock_decide:
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot=dict(_SAME_SNAP),
            no_progress_count=nav_module._STUCK_USER_THRESHOLD,
        )
        result = nav_module.navigate_to_apply(state)
    mock_decide.assert_not_called()
    assert result["nav_action"]["action"][0]["action"] == "stuck"


def test_deciding_caps_at_max_nav_steps():
    nav_module = _reload_nav()
    with _patch.dict(_os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         _patch("backend.tailorer.llm.ChatOpenAI"), \
         _patch.object(nav_module, "_decide_next_navigation") as mock_decide:
        state = _make_state(
            nav_phase="deciding",
            nav_snapshot=dict(_SAME_SNAP),
            retry_count=nav_module._MAX_NAV_STEPS,
            no_progress_count=0,
        )
        result = nav_module.navigate_to_apply(state)
    mock_decide.assert_not_called()
    assert result["nav_action"]["action"][0]["action"] == "stuck"


def test_nav_system_prompt_prioritises_search_over_scroll():
    """NAV_SYSTEM_PROMPT must instruct the agent to search before scrolling/paginating."""
    # NOTE: NAV_SYSTEM_PROMPT removed in Task 2; this test removed in Task 3
    pytest.skip("NAV_SYSTEM_PROMPT removed in Task 2; see Task 3 for new fill-only design")


def test_fill_system_prompt_declarative_format():
    from backend.tailorer.llm import FILL_SYSTEM_PROMPT
    assert "generate" in FILL_SYSTEM_PROMPT
    assert "__CV__" in FILL_SYSTEM_PROMPT
    assert "input_text" not in FILL_SYSTEM_PROMPT  # old action-name format removed
