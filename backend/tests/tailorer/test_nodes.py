import pytest
import json
import os
import importlib
from unittest.mock import AsyncMock, MagicMock, patch


def _make_state(**overrides):
    base = {
        "job_id": "abc",
        "user_id": "user1",
        "job_title": "ML Engineer",
        "job_description": "Build ML systems",
        "profile": {"first_name": "Lorenzo", "email": "l@test.com"},
        "cv_text": "Lorenzo Schiroli, ML Engineer",
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "fill_commands": [],
        "last_feedback": None,
        "retry_count": 0,
        "status": "mapping",
    }
    return {**base, **overrides}


def test_fill_system_prompt_declarative_format():
    from backend.tailorer.llm import FILL_SYSTEM_PROMPT
    assert "generate" in FILL_SYSTEM_PROMPT
    assert "__CV__" in FILL_SYSTEM_PROMPT
    assert "input_text" not in FILL_SYSTEM_PROMPT


def test_node_map_returns_fill_commands():
    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 2, "value": "Lorenzo"},
        {"index": 7, "value": "__CV__", "generate": False},
        {"index": 9, "value": "Senior", "uncertain": True},
    ])
    with patch.dict(os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         patch("backend.tailorer.llm.ChatOpenAI") as MockLLM:
        MockLLM.return_value.ainvoke = AsyncMock(return_value=mock_resp)
        from backend.tailorer import form as form_module
        importlib.reload(form_module)
        import asyncio
        state = _make_state(
            last_snapshot={"elements": "[2]<input />\n[7]<input type=file />\n[9]<select />"},
        )
        result = asyncio.run(form_module.node_map(state))

    assert len(result["fill_commands"]) == 3
    assert result["fill_commands"][0]["index"] == 2
    assert result["retry_count"] == 0
    assert result["status"] == "mapping"


def test_node_map_generates_documents_when_requested():
    mock_resp = MagicMock()
    mock_resp.content = json.dumps([
        {"index": 7, "value": "__CV__", "generate": True},
    ])
    fake_cv = b"fake-cv-bytes"
    fake_cl = b"fake-cl-bytes"

    async def fake_generate(**kwargs):
        return fake_cv, fake_cl, "cover letter text"

    with patch.dict(os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         patch("backend.tailorer.llm.ChatOpenAI") as MockLLM:
        MockLLM.return_value.ainvoke = AsyncMock(return_value=mock_resp)
        from backend.tailorer import form as form_module
        importlib.reload(form_module)
        import asyncio
        from unittest.mock import patch as p2
        with p2("backend.tailorer.tailor.generate_tailored_documents", side_effect=fake_generate), \
             p2("groq.AsyncGroq"):
            state = _make_state(
                last_snapshot={"elements": "[7]<input type=file />"},
                cv_bytes=b"",
            )
            result = asyncio.run(form_module.node_map(state))

    assert result["cv_bytes"] == fake_cv
    assert result["cl_bytes"] == fake_cl


def test_node_map_falls_back_on_json_error():
    mock_resp = MagicMock()
    mock_resp.content = "not json"
    with patch.dict(os.environ, {"GROQ_API_KEY": "k", "GROQ_MODEL_LARGE": "m"}), \
         patch("backend.tailorer.llm.ChatOpenAI") as MockLLM:
        MockLLM.return_value.ainvoke = AsyncMock(return_value=mock_resp)
        from backend.tailorer import form as form_module
        importlib.reload(form_module)
        import asyncio
        result = asyncio.run(form_module.node_map(_make_state(
            last_snapshot={"elements": "[1]<input />"},
        )))
    assert result["fill_commands"] == []
    assert result["status"] == "mapping"


def test_node_apply_returns_filled_on_clean_match():
    from backend.tailorer import form as form_module
    importlib.reload(form_module)
    with patch.object(form_module, "interrupt") as mock_interrupt:
        mock_interrupt.return_value = {
            "snapshot": {"elements": "[2]<input />"},
            "field_values": {"2": "Lorenzo"},
        }
        state = _make_state(
            fill_commands=[{"index": 2, "value": "Lorenzo"}],
            retry_count=0,
        )
        result = form_module.node_apply(state)

    assert result["status"] == "filled"
    assert result["retry_count"] == 1


def test_node_apply_loops_on_mismatch_within_retry_cap():
    from backend.tailorer import form as form_module
    importlib.reload(form_module)
    with patch.object(form_module, "interrupt") as mock_interrupt:
        mock_interrupt.return_value = {
            "snapshot": {"elements": "[2]<input />"},
            "field_values": {"2": ""},  # empty = mismatch
        }
        state = _make_state(
            fill_commands=[{"index": 2, "value": "Lorenzo"}],
            retry_count=0,
        )
        result = form_module.node_apply(state)

    assert result["status"] == "applying"
    assert result["retry_count"] == 1


def test_node_apply_stops_looping_at_retry_cap():
    from backend.tailorer import form as form_module
    importlib.reload(form_module)
    with patch.object(form_module, "interrupt") as mock_interrupt:
        mock_interrupt.return_value = {
            "snapshot": {"elements": "[2]<input />"},
            "field_values": {"2": ""},
        }
        state = _make_state(
            fill_commands=[{"index": 2, "value": "Lorenzo"}],
            retry_count=2,  # already at cap
        )
        result = form_module.node_apply(state)

    assert result["status"] == "filled"  # stops, surfaces uncertain


def test_route_after_apply_loops_on_applying():
    from backend.tailorer import agent as agent_module
    importlib.reload(agent_module)
    assert agent_module._route_after_apply(_make_state(status="applying")) == "apply"


def test_route_after_apply_ends_on_filled():
    from langgraph.graph import END
    from backend.tailorer import agent as agent_module
    importlib.reload(agent_module)
    assert agent_module._route_after_apply(_make_state(status="filled")) == END
