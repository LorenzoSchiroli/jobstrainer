# Tailorer Fill Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 7-node navigation+fill agent with a 2-node fill-only agent (map → apply) driven by a detection-first browser fill engine, with a text-first always-active panel UI.

**Architecture:** Backend collapses to `node_map` (LLM-only, declarative fill commands) and `node_apply` (interrupt, extension applies fills + returns diff, loops up to 2× on mismatch). The extension exposes a single `applyFill(index, value)` method with detection-first widget dispatch and a real file-upload chain via `chrome.downloads` + CDP `uploadFile`. The router keeps the WebSocket alive across fill passes; the panel is always-active with a Fill shortcut and New Session button.

**Tech Stack:** Python 3.12, LangGraph (AsyncPostgresSaver checkpoint), FastAPI WebSocket, puppeteer-core (ExtensionTransport / CDP), React (panel), TypeScript, Chrome Extension MV3.

**Spec:** `docs/superpowers/specs/2026-06-16-tailorer-fill-redesign-design.md`

---

## File Map

| File | Change |
|------|--------|
| `backend/backend/tailorer/state.py` | Replace — new TailorerState (strip nav_*, add fill_commands/last_feedback) |
| `backend/backend/tailorer/llm.py` | Replace FILL_SYSTEM_PROMPT; delete NAV_ and CORRECTION_ prompts |
| `backend/backend/tailorer/form.py` | Replace — new `node_map` + `node_apply`; keep `_COMPLETION_KEYWORDS` |
| `backend/backend/tailorer/agent.py` | Replace — 2-node graph with conditional loop edge |
| `backend/backend/tailorer/router.py` | Major update — new session loop, `start_or_fill` protocol, keep WS alive |
| `backend/backend/tailorer/navigation.py` | Delete |
| `backend/tests/tailorer/test_nodes.py` | Replace — new tests for map/apply/submit |
| `extension/manifest.json` | Add `"downloads"` permission |
| `extension/background/session/types.ts` | Add `summary` LogEntry kind |
| `extension/background/browser/page.ts` | Add `applyFill`, `readFieldValue`; update `snapshot()` for whole-page; remove scroll methods |
| `extension/background/agent/messageHandler.ts` | Replace handlers — `apply_fills`, `filled`, keep `session_started`/`done`/`error` |
| `extension/background/service_worker.ts` | Update port handler — `start_or_fill`, `new_session`, snapshot capture |
| `extension/sidepanel/src/App.tsx` | Replace — always-active bar, Fill button, New Session button, summary entries |

---

## Task 1: New TailorerState

**Files:**
- Modify: `backend/backend/tailorer/state.py`

- [ ] **Step 1: Write the new state**

Replace the entire file with:

```python
from typing import TypedDict


class TailorerState(TypedDict):
    # Session context (set at graph start, never mutated)
    job_id: str
    user_id: str
    job_title: str
    job_description: str
    profile: dict
    cv_text: str

    # Document bytes (built lazily by node_map when LLM requests generate=true)
    cv_bytes: bytes
    cl_bytes: bytes
    cl_text: str

    # Fill pass state (reset each pass via start_or_fill input)
    last_snapshot: dict | None      # whole-page snapshot sent with start_or_fill
    fill_commands: list[dict]        # declarative commands output by node_map
    last_feedback: str | None        # user's typed instruction for this pass
    retry_count: int                 # apply-loop counter; capped at 2
    status: str                      # mapping | applying | filled | failed
```

- [ ] **Step 2: Verify it parses**

```bash
cd backend && uv run python -c "from backend.tailorer.state import TailorerState; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/state.py
git commit -m "refactor(tailorer): replace TailorerState — strip nav_* fields, add fill_commands/last_feedback"
```

---

## Task 2: Replace LLM prompts

**Files:**
- Modify: `backend/backend/tailorer/llm.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/tailorer/test_nodes.py`, replace or add:

```python
def test_fill_system_prompt_declarative_format():
    from backend.tailorer.llm import FILL_SYSTEM_PROMPT
    assert "generate" in FILL_SYSTEM_PROMPT
    assert "__CV__" in FILL_SYSTEM_PROMPT
    assert "input_text" not in FILL_SYSTEM_PROMPT  # old action-name format removed
    assert "NAV_SYSTEM_PROMPT" not in dir(__import__("backend.tailorer.llm", fromlist=["llm"]))
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py::test_fill_system_prompt_declarative_format -v
```

Expected: FAIL (old prompt still has `input_text`, NAV_SYSTEM_PROMPT still exists)

- [ ] **Step 3: Replace llm.py**

```python
import os
from langchain_openai import ChatOpenAI

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def make_llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        api_key=os.environ["GROQ_API_KEY"],
        base_url=_GROQ_BASE_URL,
    )


def large_llm() -> ChatOpenAI:
    return make_llm(os.environ["GROQ_MODEL_LARGE"])


FILL_SYSTEM_PROMPT = (
    "You fill job application form fields from the applicant's profile and CV.\n\n"
    "Interactive elements are listed as: [index]<type attributes>text</>\n"
    "Use the numeric index to reference each element.\n\n"
    "Return a JSON array of fill commands. Each command is one of:\n"
    '  {"index": N, "value": "<text value>"}                          -- text/textarea/combobox\n'
    '  {"index": N, "value": "true"}                                   -- checkbox/radio (truthy = check)\n'
    '  {"index": N, "value": "<option text>"}                         -- select/dropdown\n'
    '  {"index": N, "value": "__CV__", "generate": true|false}        -- CV/resume file input\n'
    '  {"index": N, "value": "__COVER_LETTER__", "generate": true|false} -- cover letter file input\n\n'
    "Document status is provided in the prompt. Set generate=true only if the document has not yet been\n"
    "generated this session, or if the user explicitly asked for a new version.\n\n"
    "Add \"uncertain\": true to any command where you are not confident of the correct value.\n\n"
    "Rules:\n"
    "- NEVER fill authentication/login fields\n"
    "- Omit fields you have no data for\n"
    "- Return ONLY the JSON array, no prose, no markdown fences\n"
)
```

- [ ] **Step 4: Run test**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py::test_fill_system_prompt_declarative_format -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/backend/tailorer/llm.py backend/tests/tailorer/test_nodes.py
git commit -m "refactor(tailorer): replace LLM prompts — declarative fill format, drop NAV/CORRECTION prompts"
```

---

## Task 3: New map and apply nodes

**Files:**
- Modify: `backend/backend/tailorer/form.py`

- [ ] **Step 1: Write failing tests**

Replace `backend/tests/tailorer/test_nodes.py` entirely:

```python
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
        MockLLM.return_value.invoke.return_value = mock_resp
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
         patch("backend.tailorer.llm.ChatOpenAI") as MockLLM, \
         patch("backend.tailorer.tailor.generate_tailored_documents", side_effect=fake_generate):
        MockLLM.return_value.invoke.return_value = mock_resp
        from backend.tailorer import form as form_module
        importlib.reload(form_module)
        import asyncio
        from unittest.mock import patch as p2
        with p2("backend.tailorer.form.generate_tailored_documents", side_effect=fake_generate), \
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
        MockLLM.return_value.invoke.return_value = mock_resp
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
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py -v 2>&1 | head -40
```

Expected: Most tests FAIL (old form.py / agent.py still in place)

- [ ] **Step 3: Write new form.py**

Replace `backend/backend/tailorer/form.py` entirely:

```python
import io
import json
import logging
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from backend.tailorer.llm import large_llm, FILL_SYSTEM_PROMPT
from backend.tailorer.state import TailorerState

_log = logging.getLogger(__name__)

_COMPLETION_KEYWORDS = [
    "thank you", "application received", "successfully submitted",
    "you've applied", "you have applied", "congratulations",
    "application complete", "we'll be in touch",
]

_MAX_RETRIES = 2


async def node_map(state: TailorerState) -> TailorerState:
    """LLM-only node: reads last_snapshot, emits declarative fill commands. No interrupt."""
    from groq import AsyncGroq
    from backend.tailorer.tailor import generate_tailored_documents

    llm = large_llm()
    snapshot = state["last_snapshot"] or {}
    elements = snapshot.get("elements", "")

    cv_status = "already generated" if state.get("cv_bytes") else "not yet generated"
    cl_status = "already generated" if state.get("cl_bytes") else "not yet generated"
    feedback = f"\nUser instruction this round: {state['last_feedback']}" if state.get("last_feedback") else ""

    resp = llm.invoke([
        SystemMessage(content=FILL_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Profile:\n{json.dumps(state['profile'], indent=2)}\n\n"
            f"CV (excerpt):\n{state['cv_text'][:1500]}\n\n"
            f"Cover letter:\n{state.get('cl_text', '')[:400]}\n\n"
            f"Document status: CV: {cv_status}; Cover letter: {cl_status}\n\n"
            f"Interactive elements:\n{elements}"
            f"{feedback}"
        )),
    ])

    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    try:
        commands = json.loads(raw)
        if not isinstance(commands, list):
            raise ValueError("expected list")
    except Exception:
        _log.warning("[node_map] JSON parse failed — returning empty commands")
        return {**state, "fill_commands": [], "retry_count": 0, "status": "mapping"}

    new_cv_bytes = state.get("cv_bytes") or b""
    new_cl_bytes = state.get("cl_bytes") or b""
    new_cl_text = state.get("cl_text") or ""

    needs_cv = any(c.get("value") == "__CV__" and c.get("generate") for c in commands)
    needs_cl = any(c.get("value") == "__COVER_LETTER__" and c.get("generate") for c in commands)

    if needs_cv or needs_cl:
        if not new_cv_bytes:
            import docx as _docx
            doc = _docx.Document()
            for line in (state["cv_text"] or "").split("\n"):
                doc.add_paragraph(line)
            buf = io.BytesIO()
            doc.save(buf)
            new_cv_bytes = buf.getvalue()

        groq_client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
        try:
            new_cv_bytes, new_cl_bytes, new_cl_text = await generate_tailored_documents(
                cv_text=state["cv_text"],
                cv_bytes=new_cv_bytes,
                job_description=state["job_description"],
                groq_client=groq_client,
            )
        except Exception:
            _log.exception("[node_map] document generation failed — reusing existing bytes")

    return {
        **state,
        "fill_commands": commands,
        "cv_bytes": new_cv_bytes,
        "cl_bytes": new_cl_bytes,
        "cl_text": new_cl_text,
        "retry_count": 0,
        "status": "mapping",
    }


def node_apply(state: TailorerState) -> TailorerState:
    """Interrupt node: sends commands to extension, receives post-fill snapshot + field values.
    Loops back to itself (via conditional edge) on mismatch, bounded by _MAX_RETRIES."""
    response = interrupt({
        "type": "apply_fills",
        "commands": state["fill_commands"],
    })

    post_snapshot = response.get("snapshot", {})
    field_values: dict = response.get("field_values", {})

    mismatches: list[dict] = []
    for cmd in state["fill_commands"]:
        idx = str(cmd.get("index", ""))
        intended = str(cmd.get("value", ""))
        if intended in ("__CV__", "__COVER_LETTER__"):
            continue
        actual = str(field_values.get(idx, "")).strip()
        if actual == "" and intended:
            mismatches.append(cmd)

    new_retry = state["retry_count"] + 1

    if mismatches and new_retry <= _MAX_RETRIES:
        _log.info("[node_apply] %d mismatches, retry %d/%d", len(mismatches), new_retry, _MAX_RETRIES)
        return {**state, "last_snapshot": post_snapshot, "retry_count": new_retry, "status": "applying"}

    if mismatches:
        for cmd in mismatches:
            cmd["uncertain"] = True

    return {
        **state,
        "last_snapshot": post_snapshot,
        "retry_count": new_retry,
        "status": "filled",
    }
```

- [ ] **Step 4: Run the new node tests**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py -k "node_map or node_apply" -v
```

Expected: All node tests PASS (route tests still fail — fixed in Task 4)

- [ ] **Step 5: Commit**

```bash
git add backend/backend/tailorer/form.py backend/tests/tailorer/test_nodes.py
git commit -m "feat(tailorer): add node_map + node_apply — detection-first fill, bounded retry loop"
```

---

## Task 4: New 2-node graph

**Files:**
- Modify: `backend/backend/tailorer/agent.py`

- [ ] **Step 1: Replace agent.py**

```python
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.tailorer.state import TailorerState
from backend.tailorer.form import node_map, node_apply


def _route_after_apply(state: TailorerState) -> str:
    if state.get("status") == "applying":
        return "apply"
    return END


def build_graph(checkpointer: AsyncPostgresSaver) -> Any:
    graph = StateGraph(TailorerState)
    graph.add_node("map", node_map)
    graph.add_node("apply", node_apply)
    graph.set_entry_point("map")
    graph.add_edge("map", "apply")
    graph.add_conditional_edges("apply", _route_after_apply)
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 2: Run the route tests**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/agent.py
git commit -m "refactor(tailorer): collapse to 2-node graph (map → apply) with conditional loop edge"
```

---

## Task 5: New router session lifecycle

**Files:**
- Modify: `backend/backend/tailorer/router.py`

This is the biggest backend change. The router must:
1. Send `session_started` on WS accept, then wait for `start_or_fill` (not immediately run the graph)
2. Keep WS alive after graph END
3. Handle `submitted` (write Application row once) and `new_session` (close WS)
4. Expose one interrupt handler: `apply_fills`

- [ ] **Step 1: Replace router.py**

```python
import uuid as _uuid
import json
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.types import Command

from backend.database import get_session
from backend.models import User, Job, Company
from backend.tailorer.models import ApplicantProfile, Application
from backend.tailorer.schemas import ProfileUpsert, ProfileResponse
from backend.tailorer.state import TailorerState
from backend.tailorer.agent import build_graph
from backend.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tailorer", tags=["tailorer"])


# ── Profile endpoints (unchanged) ────────────────────────────────────────────

@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


@router.put("/profile", response_model=ProfileResponse)
async def upsert_profile(
    body: ProfileUpsert,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, val)
    await session.commit()
    await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _get_user_from_token(token: str, session: AsyncSession) -> User:
    from backend.auth.jwt import decode_access_token
    user_id = decode_access_token(token)
    if not user_id:
        raise ValueError("Invalid token")
    result = await session.execute(select(User).where(User.id == _uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    return user


# ── Interrupt handler ─────────────────────────────────────────────────────────

async def _handle_apply_fills(ws: WebSocket, val: dict, thread_id: str = "", token: str = "") -> dict:
    await ws.send_json({
        "type": "apply_fills",
        "commands": val.get("commands", []),
        "thread_id": thread_id,
        "token": token,
    })
    return await ws.receive_json()


async def _handle_interrupt(ws: WebSocket, interrupt_val: dict, thread_id: str = "", token: str = "") -> dict:
    if interrupt_val.get("type") == "apply_fills":
        return await _handle_apply_fills(ws, interrupt_val, thread_id=thread_id, token=token)
    logger.warning("[tailorer] unknown interrupt type: %s", interrupt_val.get("type"))
    return {"type": "unknown"}


# ── WebSocket session ─────────────────────────────────────────────────────────

@router.websocket("/ws/{job_id}")
async def tailorer_ws(
    websocket: WebSocket,
    job_id: _uuid.UUID,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    job_result = await session.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return

    profile_result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.cv_text:
        await websocket.send_json({"type": "error", "message": "No CV on file. Upload your CV first."})
        await websocket.close()
        return

    thread_id = str(_uuid.uuid4())
    await websocket.send_json({"type": "session_started", "thread_id": thread_id})

    config = {"configurable": {"thread_id": thread_id}}

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    graph = build_graph(checkpointer)

    base_state: TailorerState = {
        "job_id": str(job.id),
        "user_id": str(user.id),
        "job_title": job.title,
        "job_description": job.description or "",
        "profile": {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "city": profile.city,
            "country": profile.country,
            "work_auth": profile.work_auth,
            "urls": profile.urls or {},
            "extra_qa": profile.extra_qa or {},
        },
        "cv_text": profile.cv_text or "",
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "fill_commands": [],
        "last_feedback": None,
        "retry_count": 0,
        "status": "mapping",
    }

    is_first_pass = True

    try:
        while True:  # outer: keep WS alive across fill passes
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "new_session":
                logger.info("[tailorer] new_session requested — closing WS")
                break

            if msg_type == "submitted":
                logger.info("[tailorer] submit detected — writing Application row")
                try:
                    app_record = Application(user_id=user.id, job_id=job_id)
                    session.add(app_record)
                    await session.commit()
                    await websocket.send_json({"type": "application_recorded"})
                except Exception:
                    await session.rollback()
                    logger.warning("[tailorer] Application row already exists or write failed")
                continue

            if msg_type != "start_or_fill":
                logger.warning("[tailorer] unexpected message type=%s — ignored", msg_type)
                continue

            snapshot = msg.get("snapshot")
            feedback_text = msg.get("text", "")

            if is_first_pass:
                current_input: Any = {
                    **base_state,
                    "last_snapshot": snapshot,
                    "last_feedback": feedback_text or None,
                }
                is_first_pass = False
            else:
                current_input = {
                    "last_snapshot": snapshot,
                    "last_feedback": feedback_text or None,
                    "retry_count": 0,
                    "status": "mapping",
                    "fill_commands": [],
                }

            # inner: drive map → apply (with interrupt loop) to END
            while True:
                await graph.ainvoke(current_input, config)
                state_snap = await graph.aget_state(config)

                if not state_snap.next:
                    values = state_snap.values or {}
                    final_status = values.get("status")
                    fill_commands = values.get("fill_commands", [])
                    uncertain = [str(c["index"]) for c in fill_commands if c.get("uncertain")]

                    if final_status == "filled":
                        await websocket.send_json({
                            "type": "filled",
                            "filled_count": len(fill_commands),
                            "uncertain_fields": uncertain,
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Fill pass failed (status: {final_status})",
                        })
                    break  # back to outer loop — wait for next start_or_fill

                interrupts = [i for task in state_snap.tasks for i in task.interrupts]
                if not interrupts:
                    logger.warning("[tailorer] graph not done but no interrupts — breaking")
                    break

                logger.info("[tailorer] interrupt: %s", interrupts[0].value.get("type"))
                resume_val = await _handle_interrupt(
                    websocket, interrupts[0].value, thread_id=thread_id, token=token
                )
                current_input = Command(resume=resume_val)

    except WebSocketDisconnect:
        logger.info("[tailorer] WebSocket disconnected")
    except Exception as e:
        logger.exception("[tailorer] unhandled exception: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── File download endpoint (unchanged) ───────────────────────────────────────

@router.get("/files/{thread_id}/{file_type}")
async def download_tailored_file(
    thread_id: str,
    file_type: str,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    from fastapi.responses import Response
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid token")

    if file_type not in ("cv", "cover_letter"):
        raise HTTPException(status_code=400, detail="file_type must be 'cv' or 'cover_letter'")

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_graph(checkpointer)
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot or not state_snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found")

    values = state_snapshot.values
    if values.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    key = "cv_bytes" if file_type == "cv" else "cl_bytes"
    file_bytes = values.get(key, b"")
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not yet generated")

    filename = "tailored_cv.docx" if file_type == "cv" else "cover_letter.docx"
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 2: Delete navigation.py**

```bash
rm backend/backend/tailorer/navigation.py
```

- [ ] **Step 3: Run all backend tailorer tests**

```bash
cd backend && uv run pytest tests/tailorer/ -v
```

Expected: All tests PASS

- [ ] **Step 4: Verify backend starts without import errors**

```bash
cd backend && uv run python -c "from backend.tailorer.router import router; from backend.tailorer.agent import build_graph; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/backend/tailorer/router.py backend/backend/tailorer/navigation.py backend/backend/tailorer/agent.py
git commit -m "feat(tailorer): new router — start_or_fill protocol, persistent WS, submitted/new_session lifecycle"
```

---

## Task 6: Backend integration test for submitted idempotency

**Files:**
- Modify: `backend/tests/tailorer/test_nodes.py`

- [ ] **Step 1: Add idempotency test**

Append to `backend/tests/tailorer/test_nodes.py`:

```python
def test_fill_system_prompt_has_no_nav_prompt():
    import backend.tailorer.llm as llm_mod
    assert not hasattr(llm_mod, "NAV_SYSTEM_PROMPT")
    assert not hasattr(llm_mod, "CORRECTION_SYSTEM_PROMPT")


def test_new_state_has_no_nav_fields():
    import typing
    from backend.tailorer.state import TailorerState
    hints = typing.get_type_hints(TailorerState)
    for nav_field in ("nav_phase", "nav_snapshot", "nav_action", "nav_history", "no_progress_count", "apply_url", "current_page", "filled_fields", "pending_correction"):
        assert nav_field not in hints, f"nav field {nav_field!r} should be removed"
    for new_field in ("fill_commands", "last_feedback", "retry_count"):
        assert new_field in hints, f"new field {new_field!r} missing"
```

- [ ] **Step 2: Run**

```bash
cd backend && uv run pytest tests/tailorer/ -v
```

Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/tailorer/test_nodes.py
git commit -m "test(tailorer): verify new state shape and removed prompts"
```

---

## Task 7: Extension manifest — add downloads permission

**Files:**
- Modify: `extension/manifest.json`

- [ ] **Step 1: Add downloads permission**

In `extension/manifest.json`, change:
```json
"permissions": [
    "tabs",
    "scripting",
    "sidePanel",
    "alarms",
    "storage",
    "debugger",
    "webNavigation"
  ],
```
to:
```json
"permissions": [
    "tabs",
    "scripting",
    "sidePanel",
    "alarms",
    "storage",
    "debugger",
    "webNavigation",
    "downloads"
  ],
```

- [ ] **Step 2: Commit**

```bash
git add extension/manifest.json
git commit -m "feat(extension): add downloads permission for automated file upload chain"
```

---

## Task 8: Update session types

**Files:**
- Modify: `extension/background/session/types.ts`

- [ ] **Step 1: Add summary LogEntry kind**

Replace the `LogEntry` type in `extension/background/session/types.ts`:

```typescript
import type Page from '../browser/page';

export interface FileLink {
  field_id: number;
  label: string;
  url: string;
}

export type LogEntry =
  | { kind: 'step'; text: string; done: boolean }
  | { kind: 'summary'; filled_count: number; uncertain_fields: string[]; file_links: FileLink[] }
  | { kind: 'error'; message: string };

export interface PendingJob {
  job_id: string;
  token: string;
}

export interface Session {
  job_id: string;
  token: string;
  thread_id: string | null;
  ws: WebSocket;
  page: Page;
  log: LogEntry[];
  currentStatus: string;
}
```

- [ ] **Step 2: Commit**

```bash
git add extension/background/session/types.ts
git commit -m "refactor(extension): simplify LogEntry — add summary kind, remove confirm/stuck/done"
```

---

## Task 9: applyFill + whole-page snapshot in page.ts

**Files:**
- Modify: `extension/background/browser/page.ts`

The current `getClickableElements` signature is:
```
getClickableElements(tabId, url, showHighlightElements=true, focusElement=-1, viewportExpansion=0)
```
Pass `viewportExpansion=-1` to serialize the whole page.

- [ ] **Step 1: Update PageSnapshot type and snapshot() method**

In `page.ts`, change the `PageSnapshot` interface — remove scroll fields:

```typescript
export interface PageSnapshot {
  url: string;
  title: string;
  elements: string;
}
```

Update `snapshot()` — remove `getScrollInfo` call, pass `viewportExpansion=-1`:

```typescript
async snapshot(): Promise<PageSnapshot> {
  await this.waitForPageAndFramesLoad();
  const tab = await chrome.tabs.get(this._tabId);
  const url = tab.url ?? '';
  const title = tab.title ?? '';
  const domState: DOMState = await getClickableElements(this._tabId, url, true, -1, -1);
  this._lastSelectorMap = domState.selectorMap;
  const elements = domState.elementTree.clickableElementsToString();
  return { url, title, elements };
}
```

Remove the `getScrollInfo` import from the top-level import line. Also remove `scrollDown`, `scrollUp`, `scrollToTop`, `scrollToBottom` methods from the class.

- [ ] **Step 2: Add the file-upload helper**

Add this private method to the `Page` class (before `_addAntiDetectionScripts`):

```typescript
private async _uploadFile(el: ElementHandle, value: string, threadId: string, token: string): Promise<void> {
  const fileType = value === '__CV__' ? 'cv' : 'cover_letter';
  const filename = value === '__CV__' ? 'tailored_cv.docx' : 'cover_letter.docx';
  const url = `http://localhost:8000/tailorer/files/${threadId}/${fileType}?token=${encodeURIComponent(token)}`;

  const downloadId = await new Promise<number>((resolve, reject) => {
    chrome.downloads.download(
      { url, filename: `tailorer/${filename}`, conflictAction: 'overwrite' },
      (id) => {
        if (chrome.runtime.lastError) reject(new Error(String(chrome.runtime.lastError.message)));
        else resolve(id!);
      },
    );
  });

  const absolutePath = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Download timeout')), 30_000);
    const listener = (delta: chrome.downloads.DownloadDelta) => {
      if (delta.id !== downloadId) return;
      if (delta.state?.current === 'complete') {
        clearTimeout(timer);
        chrome.downloads.onChanged.removeListener(listener);
        chrome.downloads.search({ id: downloadId }, (items) => {
          const path = items[0]?.filename;
          if (path) resolve(path);
          else reject(new Error('Download path not found'));
        });
      } else if (delta.state?.current === 'interrupted') {
        clearTimeout(timer);
        chrome.downloads.onChanged.removeListener(listener);
        reject(new Error('Download interrupted'));
      }
    };
    chrome.downloads.onChanged.addListener(listener);
  });

  await el.uploadFile(absolutePath);

  chrome.downloads.removeFile(downloadId, () => {});
  chrome.downloads.erase({ id: downloadId }, () => {});
}
```

- [ ] **Step 3: Add applyFill and readFieldValue methods**

Add after `selectOption`:

```typescript
async applyFill(index: number, value: string, threadId = '', token = ''): Promise<void> {
  const node = await this._getElementNode(index);
  const el = await this._locateHandle(node);
  await this._scrollIntoViewIfNeeded(el);

  const kind = await el.evaluate((node: Element): string => {
    const tag = node.tagName.toLowerCase();
    const type = ((node as HTMLInputElement).type ?? '').toLowerCase();
    const role = (node.getAttribute('role') ?? '').toLowerCase();
    const hasPopup = node.hasAttribute('aria-haspopup');
    const ce = node.getAttribute('contenteditable');
    if (tag === 'input' && (type === 'checkbox' || type === 'radio')) return 'checkbox';
    if (tag === 'select') return 'select';
    if (tag === 'input' && type === 'file') return 'file';
    if (role === 'combobox' || role === 'listbox' || hasPopup) return 'combobox';
    if (ce === 'true' || ce === '') return 'contenteditable';
    return 'text';
  });

  switch (kind) {
    case 'checkbox': {
      const checked = ['true', '1', 'yes'].includes(value.toLowerCase());
      await el.evaluate((node: Element, val: boolean) => {
        const input = node as HTMLInputElement;
        if (input.checked !== val) {
          input.checked = val;
          input.dispatchEvent(new Event('change', { bubbles: true }));
          input.click();
        }
      }, checked);
      break;
    }
    case 'select':
      await el.evaluate((node: Element, val: string) => {
        const select = node as HTMLSelectElement;
        const opt = Array.from(select.options).find((o) => o.text === val || o.value === val);
        if (opt) select.value = opt.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }, value);
      break;
    case 'combobox': {
      await el.click();
      await new Promise((r) => setTimeout(r, 250));
      const page = this._requirePage();
      await page.evaluate((val: string) => {
        const candidates = document.querySelectorAll('[role="option"], [data-value], li');
        for (const opt of candidates) {
          if ((opt as HTMLElement).innerText?.trim() === val) {
            (opt as HTMLElement).click();
            return;
          }
        }
      }, value);
      break;
    }
    case 'file':
      try {
        await this._uploadFile(el, value, threadId, token);
      } catch (e) {
        logger.error('[Page] file upload failed — caller should fall back to download link', e);
        throw e;
      }
      break;
    case 'contenteditable':
      await el.evaluate((node: Element, val: string) => {
        const el = node as HTMLElement;
        el.focus();
        el.textContent = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }, value);
      break;
    default: {
      // React-safe native setter
      await el.evaluate((node: Element, val: string) => {
        if (!(node instanceof HTMLInputElement) && !(node instanceof HTMLTextAreaElement)) return;
        node.focus();
        node.select();
        const proto = node instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(node, val);
        else node.value = val;
        node.dispatchEvent(new Event('input', { bubbles: true }));
        node.dispatchEvent(new Event('change', { bubbles: true }));
      }, value);
      break;
    }
  }
}

async readFieldValue(index: number): Promise<string> {
  try {
    const node = await this._getElementNode(index);
    const el = await this._locateHandle(node);
    return await el.evaluate((node: Element): string => {
      const tag = node.tagName.toLowerCase();
      const type = ((node as HTMLInputElement).type ?? '').toLowerCase();
      if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
        return (node as HTMLInputElement).checked ? 'true' : 'false';
      }
      if ('value' in node) return (node as HTMLInputElement).value ?? '';
      return (node as HTMLElement).textContent?.trim() ?? '';
    });
  } catch {
    return '';
  }
}
```

- [ ] **Step 4: Build the extension**

```bash
cd extension && npm run build 2>&1 | tail -20
```

Expected: Build completes with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add extension/background/browser/page.ts
git commit -m "feat(extension): add applyFill (detection-first dispatch), readFieldValue, whole-page snapshot"
```

---

## Task 10: Update messageHandler

**Files:**
- Modify: `extension/background/agent/messageHandler.ts`

- [ ] **Step 1: Replace messageHandler.ts**

```typescript
import { sessionManager } from '../session/manager';
import type { Session } from '../session/types';

const API_BASE = 'http://localhost:8000';

type Handler = (
  tabId: number,
  session: Session,
  msg: Record<string, unknown>,
) => Promise<void>;

const HANDLERS: Record<string, Handler> = {
  session_started: async (_tabId, session, msg) => {
    session.thread_id = msg.thread_id as string;
    session.currentStatus = 'idle';
  },

  apply_fills: async (tabId, session, msg) => {
    session.currentStatus = 'filling';
    await session.page.attach();

    const commands = msg.commands as Record<string, unknown>[];
    const threadId = msg.thread_id as string ?? session.thread_id ?? '';
    const token = msg.token as string ?? session.token;

    sessionManager.appendLog(tabId, { kind: 'step', text: `Filling ${commands.length} fields…`, done: false });

    const fieldValues: Record<string, string> = {};
    const fileFailedIndices = new Set<string>();

    for (const cmd of commands) {
      const idx = cmd.index as number;
      const value = cmd.value as string;
      try {
        await session.page.applyFill(idx, value, threadId, token);
        fieldValues[String(idx)] = await session.page.readFieldValue(idx);
      } catch (e) {
        console.warn('[tailorer] applyFill failed', cmd, e);
        if (value === '__CV__' || value === '__COVER_LETTER__') {
          fileFailedIndices.add(String(idx));
        }
        fieldValues[String(idx)] = '';
      }
    }

    // Persist file commands + failures so the filled handler can build download links
    (session as any)._lastFileCommands = commands.filter(
      (c) => c.value === '__CV__' || c.value === '__COVER_LETTER__',
    );
    (session as any)._lastFileFailedIndices = fileFailedIndices;

    const snap = await session.page.snapshot();

    sessionManager.appendLog(tabId, { kind: 'step', text: `Filling ${commands.length} fields…`, done: true });

    session.ws.send(JSON.stringify({
      type: 'fill_result',
      snapshot: snap,
      field_values: fieldValues,
    }));
  },

  filled: async (tabId, session, msg) => {
    session.currentStatus = 'idle';
    const filledCount = msg.filled_count as number ?? 0;
    const uncertainFields = msg.uncertain_fields as string[] ?? [];

    // Build download links for file commands where upload failed
    const lastFileCmds: Array<Record<string, unknown>> = (session as any)._lastFileCommands ?? [];
    const failedIds: Set<string> = (session as any)._lastFileFailedIndices ?? new Set();
    const fileLinks = lastFileCmds
      .filter((c) => failedIds.has(String(c.index)))
      .map((c) => ({
        field_id: c.index as number,
        label: c.value === '__CV__' ? 'tailored_cv.docx' : 'cover_letter.docx',
        url: `${API_BASE}/tailorer/files/${session.thread_id}/${c.value === '__CV__' ? 'cv' : 'cover_letter'}?token=${encodeURIComponent(session.token)}`,
      }));

    sessionManager.appendLog(tabId, {
      kind: 'summary',
      filled_count: filledCount,
      uncertain_fields: uncertainFields,
      file_links: fileLinks,
    });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'idle' });
  },

  application_recorded: async (tabId, _session, _msg) => {
    sessionManager.appendLog(tabId, { kind: 'step', text: 'Application recorded', done: true });
  },

  error: async (tabId, session, msg) => {
    session.currentStatus = 'error';
    sessionManager.appendLog(tabId, { kind: 'error', message: msg.message as string });
    sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'error' });
  },
};

export async function handleAgentMessage(
  tabId: number,
  msg: Record<string, unknown>,
): Promise<void> {
  const session = sessionManager.get(tabId);
  if (!session) return;
  const handler = HANDLERS[msg.type as string];
  if (!handler) {
    console.warn('[tailorer] unhandled message type:', msg.type);
    return;
  }
  await handler(tabId, session, msg);
}
```

- [ ] **Step 2: Build**

```bash
cd extension && npm run build 2>&1 | tail -20
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add extension/background/agent/messageHandler.ts
git commit -m "feat(extension): new messageHandler — apply_fills + filled/error; remove navigation handlers"
```

---

## Task 11: Update service_worker

**Files:**
- Modify: `extension/background/service_worker.ts`

The service worker must:
- On `start_or_fill` from panel: create session if needed, take snapshot, forward to backend WS
- On `new_session`: stop session, reset panel to idle
- Remove `start_session` handling (replaced by `start_or_fill`)
- Keep Stop and keepalive logic

- [ ] **Step 1: Replace service_worker.ts**

```typescript
import { sessionManager } from './session/manager';
import { handleAgentMessage } from './agent/messageHandler';

// ── Keepalive ──────────────────────────────────────────────────────────────
chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== 'keepalive') return;
  chrome.storage.local.set({ activeSessions: sessionManager.activeSessions() });
});

// ── Tab lifecycle ──────────────────────────────────────────────────────────
chrome.tabs.onCreated.addListener(async (tab) => {
  if (!tab.openerTabId || !tab.id) return;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.openerTabId },
      func: () => ({
        pending: localStorage.getItem('tailorer_pending'),
        token: localStorage.getItem('access_token'),
      }),
    });
    const { pending, token } = result.result as { pending: string | null; token: string | null };
    if (pending && token) {
      const { job_id } = JSON.parse(pending) as { job_id: string };
      await chrome.scripting.executeScript({
        target: { tabId: tab.openerTabId },
        func: () => localStorage.removeItem('tailorer_pending'),
      });
      sessionManager.setPending(tab.id, { job_id, token });
      chrome.sidePanel?.open?.({ tabId: tab.id }).catch(() => {});
    }
  } catch (_) {}
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  const pending = sessionManager.getPending(tabId);
  const session = sessionManager.get(tabId);
  if (!pending && !session) return;
  chrome.sidePanel?.open?.({ tabId }).catch(() => {});
  if (pending) {
    sessionManager.sendToPanel(tabId, { type: 'show_job_context', job_id: pending.job_id, token: pending.token });
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  sessionManager.cleanupTab(tabId);
});

// ── Panel ports ────────────────────────────────────────────────────────────
chrome.runtime.onConnect.addListener((port) => {
  const match = port.name.match(/^panel-(\d+)$/);
  if (!match) return;
  const tabId = parseInt(match[1]);
  sessionManager.registerPort(tabId, port);

  port.onDisconnect.addListener(() => {
    sessionManager.removePort(tabId);
  });

  const pending = sessionManager.getPending(tabId);
  const session = sessionManager.get(tabId);
  if (pending) {
    port.postMessage({ type: 'show_job_context', job_id: pending.job_id, token: pending.token });
  } else if (session) {
    const wsAlive = session.ws.readyState === WebSocket.OPEN;
    port.postMessage({
      type: 'restore_panel',
      log: session.log,
      status: wsAlive ? session.currentStatus : 'error',
    });
  } else {
    chrome.storage.local.get('activeSessions', ({ activeSessions }) => {
      const saved = (activeSessions as any[] || []).find((s: any) => s.tabId === tabId);
      if (saved) {
        port.postMessage({
          type: 'restore_panel',
          log: [...saved.log, { kind: 'error', message: 'Connection lost — restart session.' }],
          status: 'error',
        });
      } else {
        port.postMessage({ type: 'idle' });
      }
    });
  }

  port.onMessage.addListener(async (msg: any) => {
    if (msg.type === 'stop_session') {
      if (sessionManager.has(tabId)) {
        sessionManager.stop(tabId, 'Stopped by user.');
      } else {
        sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'idle' });
      }
      return;
    }

    if (msg.type === 'new_session') {
      if (sessionManager.has(tabId)) {
        sessionManager.stop(tabId, 'New session started.');
      }
      sessionManager.sendToPanel(tabId, { type: 'idle' });
      return;
    }

    if (msg.type === 'append_optimistic_log') {
      const s = sessionManager.get(tabId);
      if (s) s.log.push(msg.entry as any);
      return;
    }

    if (msg.type === 'start_or_fill') {
      const feedbackText: string = msg.text ?? '';
      const pending = sessionManager.getPending(tabId);
      const session = sessionManager.get(tabId);

      const job_id: string = session?.job_id ?? pending?.job_id ?? '';
      const token: string = session?.token ?? pending?.token ?? '';

      if (!job_id || !token) {
        sessionManager.sendToPanel(tabId, { type: 'error_toast', message: 'No active job — open a job first.' });
        return;
      }

      // Open session (and WS) if not already open
      if (!session) {
        sessionManager.clearPending(tabId);
        sessionManager.open(tabId, job_id, token, handleAgentMessage);
      }

      // Wait for the session to exist
      const activeSession = sessionManager.get(tabId);
      if (!activeSession) return;

      // Capture whole-page snapshot
      try {
        await activeSession.page.attach();
        const snapshot = await activeSession.page.snapshot();
        const wsMsg = JSON.stringify({ type: 'start_or_fill', text: feedbackText, snapshot });

        if (activeSession.ws.readyState === WebSocket.OPEN) {
          activeSession.ws.send(wsMsg);
        } else {
          // WS still connecting — queue the send
          activeSession.ws.addEventListener('open', () => activeSession.ws.send(wsMsg), { once: true });
        }
      } catch (e) {
        console.error('[tailorer] snapshot failed during start_or_fill', e);
        sessionManager.sendToPanel(tabId, { type: 'set_status', status: 'error' });
      }
      return;
    }

    // Forward submitted signal
    if (msg.type === 'submitted') {
      const s = sessionManager.get(tabId);
      if (s?.ws.readyState === WebSocket.OPEN) {
        s.ws.send(JSON.stringify({ type: 'submitted' }));
      }
      return;
    }
  });
});
```

- [ ] **Step 2: Build**

```bash
cd extension && npm run build 2>&1 | tail -20
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add extension/background/service_worker.ts
git commit -m "feat(extension): new service_worker — start_or_fill protocol, new_session, snapshot capture"
```

---

## Task 12: New App.tsx — text-first UI

**Files:**
- Modify: `extension/sidepanel/src/App.tsx`

Removes: `pendingJob` / "Start Agent" button, `isWaiting` gate, `ConfirmBlock`.  
Adds: always-active bar, **Fill** shortcut button, **New Session** header button, `summary` log entry rendering.

- [ ] **Step 1: Replace App.tsx**

```tsx
import React, { useEffect, useRef, useState, useCallback } from 'react';
import LogEntry from './components/LogEntry';
import StatusBar from './components/StatusBar';
import type { LogEntry as LogItem } from '../../background/session/types';

export default function App() {
  const [log, setLog] = useState<LogItem[]>([]);
  const [status, setStatus] = useState('idle');
  const [jobContext, setJobContext] = useState<{ job_id: string; token: string } | null>(null);
  const [inputText, setInputText] = useState('');
  const portRef = useRef<chrome.runtime.Port | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const isActive = ['connecting', 'filling'].includes(status);
  const hasJob = jobContext !== null || status !== 'idle';

  useEffect(() => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) return;
      const port = chrome.runtime.connect({ name: `panel-${tab.id}` });
      portRef.current = port;

      port.onMessage.addListener((msg: any) => {
        if (msg.type === 'idle') { setStatus('idle'); setLog([]); setJobContext(null); return; }
        if (msg.type === 'show_job_context') { setJobContext({ job_id: msg.job_id, token: msg.token }); return; }
        if (msg.type === 'restore_panel') { setLog(msg.log ?? []); setStatus(msg.status ?? 'idle'); return; }
        if (msg.type === 'append_log') { setLog(prev => [...prev, msg.entry]); return; }
        if (msg.type === 'set_status') { setStatus(msg.status); return; }
        if (msg.type === 'error_toast') {
          setLog(prev => [...prev, { kind: 'error', message: msg.message }]);
          return;
        }
      });

      port.onDisconnect.addListener(() => { portRef.current = null; });
    });
  }, []);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [log]);

  const sendMsg = useCallback((msg: any) => { portRef.current?.postMessage(msg); }, []);

  const handleSend = useCallback((overrideText?: string) => {
    const text = (overrideText ?? inputText).trim();
    if (!text) return;
    setInputText('');
    setLog(prev => [...prev, { kind: 'step', text, done: false }]);
    sendMsg({ type: 'start_or_fill', text });
  }, [inputText, sendMsg]);

  const handleNewSession = useCallback(() => {
    setLog([]);
    setStatus('idle');
    sendMsg({ type: 'new_session' });
  }, [sendMsg]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#f1f5f9', fontFamily: 'system-ui, sans-serif', fontSize: 12 }}>
      {/* Header */}
      <div style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid rgba(14,165,233,0.2)', flexShrink: 0 }}>
        <div style={{ width: 22, height: 22, background: '#0ea5e9', borderRadius: '50%' }} />
        <span style={{ fontWeight: 700, color: '#7dd3fc', fontSize: 13 }}>Tailorer</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <StatusBar status={status} />
          <button
            onClick={handleNewSession}
            style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 5, padding: '3px 8px', fontSize: 11, cursor: 'pointer' }}
          >New Session</button>
        </div>
      </div>

      {/* Feed */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {status === 'idle' && log.length === 0 && (
          <div style={{ color: '#475569', textAlign: 'center', marginTop: 40, lineHeight: 1.6 }}>
            {hasJob ? 'Navigate to the application form, then click Fill.' : 'No active job — browse to a job listing.'}
          </div>
        )}

        {log.length > 0 && (
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ width: 24, height: 24, borderRadius: '50%', background: '#0c4a6e', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, color: '#38bdf8', fontWeight: 700 }}>A</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#0ea5e9', marginBottom: 5, letterSpacing: '0.04em' }}>AGENT</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {log.map((entry, i) => {
                  if (entry.kind === 'step') return <LogEntry key={i} text={entry.text} done={entry.done} />;
                  if (entry.kind === 'summary') return (
                    <div key={i} style={{ background: '#1e293b', borderRadius: 6, padding: '8px 10px', fontSize: 11 }}>
                      <div style={{ color: '#86efac', fontWeight: 600, marginBottom: 4 }}>✓ Filled {entry.filled_count} field{entry.filled_count !== 1 ? 's' : ''}</div>
                      {entry.uncertain_fields.length > 0 && (
                        <div style={{ color: '#fcd34d' }}>Uncertain: fields [{entry.uncertain_fields.join(', ')}] — check manually</div>
                      )}
                      {entry.file_links.map((fl, j) => (
                        <div key={j} style={{ marginTop: 4 }}>
                          <a href={fl.url} download={fl.label} style={{ color: '#38bdf8', textDecoration: 'none' }}>↓ {fl.label}</a>
                        </div>
                      ))}
                    </div>
                  );
                  if (entry.kind === 'error') return <div key={i} style={{ color: '#fca5a5' }}>✗ {entry.message}</div>;
                  return null;
                })}
              </div>
            </div>
          </div>
        )}
        <div ref={logEndRef} />
      </div>

      {/* Fill shortcut + input bar */}
      <div style={{ borderTop: '1px solid #1e293b', padding: '6px 10px 4px', flexShrink: 0 }}>
        <button
          onClick={() => handleSend('fill the form')}
          disabled={isActive}
          style={{ width: '100%', background: isActive ? '#1e293b' : '#0ea5e9', color: isActive ? '#334155' : '#fff', border: 'none', borderRadius: 6, padding: '7px', fontWeight: 600, fontSize: 12, cursor: isActive ? 'not-allowed' : 'pointer', marginBottom: 6 }}
        >Fill</button>
        <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
          <input
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder={isActive ? 'Filling…' : 'Type an instruction or correction…'}
            style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 6, padding: '6px 9px', color: '#f1f5f9', fontSize: 12, fontFamily: 'system-ui', outline: 'none' }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!inputText.trim() || isActive}
            style={{ background: inputText.trim() && !isActive ? '#0ea5e9' : '#1e293b', color: inputText.trim() && !isActive ? '#fff' : '#334155', border: 'none', borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: inputText.trim() && !isActive ? 'pointer' : 'not-allowed', flexShrink: 0 }}
          >▶</button>
          <button
            onClick={() => sendMsg({ type: 'stop_session' })}
            disabled={!isActive}
            style={{ background: isActive ? '#7f1d1d' : '#1e293b', color: isActive ? '#fca5a5' : '#334155', border: `1px solid ${isActive ? '#991b1b' : '#1e293b'}`, borderRadius: 5, padding: '6px 10px', fontSize: 11, cursor: isActive ? 'pointer' : 'not-allowed', flexShrink: 0 }}
          >■ Stop</button>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
      `}</style>
    </div>
  );
}
```

- [ ] **Step 2: Build**

```bash
cd extension && npm run build 2>&1 | tail -20
```

If TypeScript complains about the `LogEntry` import path, adjust the relative import. The `types.ts` export adds `summary` — verify the import resolves. If `ConfirmBlock` is no longer used, you can delete `extension/sidepanel/src/components/ConfirmBlock.tsx` (check it's not imported elsewhere first).

- [ ] **Step 3: Commit**

```bash
git add extension/sidepanel/src/App.tsx
git commit -m "feat(panel): text-first UI — always-active bar, Fill button, New Session, summary entries"
```

---

## Task 13: Clean up unused files and imports

**Files:**
- Delete: `extension/sidepanel/src/components/ConfirmBlock.tsx` (if unused)
- Check: any remaining import of `navigation.py` or `CORRECTION_SYSTEM_PROMPT`

- [ ] **Step 1: Check for stale imports**

```bash
grep -r "navigation\|CORRECTION_SYSTEM_PROMPT\|ConfirmBlock\|fill_and_confirm\|navigate_next\|show_stuck\|user_approved\|user_correction\|stuck_unblocked" \
  backend/backend/tailorer/ extension/background/ extension/sidepanel/src/ \
  --include="*.py" --include="*.ts" --include="*.tsx" -l
```

- [ ] **Step 2: Remove ConfirmBlock if only used in old App.tsx**

```bash
grep -r "ConfirmBlock" extension/sidepanel/src/ --include="*.tsx"
```

If the only hit is the component file itself (not imported anywhere), delete it:

```bash
rm extension/sidepanel/src/components/ConfirmBlock.tsx
```

- [ ] **Step 3: Final build**

```bash
cd extension && npm run build && cd ../backend && uv run pytest tests/tailorer/ -v
```

Expected: Build clean, all tailorer tests PASS.

- [ ] **Step 4: Final commit**

```bash
git add -u
git commit -m "chore(tailorer): remove unused ConfirmBlock, nav imports, and stale code"
```

---

## End-to-End Smoke Test

After all tasks:

1. Start backend: `cd backend && uv run uvicorn backend.main:app --reload`
2. Load the extension in Chrome (unpacked from `extension/dist/`)
3. Open a job listing page that was already in the DB → side panel opens
4. Navigate manually to the application form
5. Click **Fill** in the panel
6. Verify: the agent fills the form fields; non-blocking summary entry appears (no modal, no "approve" step)
7. Type a correction (e.g., "change seniority to Senior") → agent re-fills
8. Advance to the next form page → click Fill again; same WS session, same thread
9. Click **New Session** → panel resets to idle
10. On a real submit (user clicks site's Submit button) → Application row appears in DB via `submitted` signal
