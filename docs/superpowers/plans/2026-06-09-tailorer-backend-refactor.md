# Tailorer Backend Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `backend/tailorer/nodes.py` (370-line monolith) into `llm.py`, `navigation.py`, and `form.py`; refactor `router.py`'s interrupt handling from a single if/elif chain into a dispatch map.

**Architecture:** Pure extraction — logic is not changed, only moved. `llm.py` owns the LLM factory and all prompt constants. `navigation.py` owns the ReAct navigation loop and its helpers. `form.py` owns form-filling nodes and helpers. `router.py` gains a `_INTERRUPT_HANDLERS` dispatch dict replacing `_handle_interrupt`'s if/elif chain. `nodes.py` is deleted at the end.

**Tech Stack:** Python 3.12, LangGraph, LangChain OpenAI, FastAPI, pytest, uv

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/backend/tailorer/llm.py` | LLM factory (`make_llm`, `large_llm`) + all system prompt constants |
| Create | `backend/backend/tailorer/navigation.py` | `navigate_to_apply` node + `_decide_next_navigation`, `_next_no_progress`, `_resolve_url`, nav constants |
| Create | `backend/backend/tailorer/form.py` | `confirm_apply`, `tailor_documents`, `fetch_snapshot`, `fill_page`, `navigate_next`, `node_done` + `_map_fields`, `_apply_correction` |
| Modify | `backend/backend/tailorer/agent.py` | Update imports: `navigation` + `form` instead of `nodes` |
| Modify | `backend/backend/tailorer/router.py` | Replace `_handle_interrupt` if/elif with dispatch map |
| Modify | `backend/tests/tailorer/test_nodes.py` | Update all imports and patches to point to new modules |
| Delete | `backend/backend/tailorer/nodes.py` | Replaced by `navigation.py` + `form.py` |

---

### Task 1: Create `llm.py`

**Files:**
- Create: `backend/backend/tailorer/llm.py`

- [ ] **Step 1: Create the file**

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


NAV_SYSTEM_PROMPT = (
    "You are navigating a company website to find the job application form.\n\n"
    "# Input Format\n"
    "Interactive elements are listed as: [index]<type attributes>text</>\n"
    "Only elements with [index] are interactive. Use the index to reference them.\n\n"
    "# Response Format\n"
    'Return ONLY valid JSON:\n'
    '{"current_state": {"evaluation_previous_goal": "<Success|Failed|Unknown — why>", '
    '"memory": "<what you have done, what remains>", '
    '"next_goal": "<immediate next action>"}, '
    '"action": [{"action": "<name>", ...params}]}\n\n'
    "# Available actions\n"
    '{"action": "click_element", "index": N}\n'
    '{"action": "go_to_url", "url": "<absolute url>"}\n'
    '{"action": "scroll_to_bottom"}\n'
    '{"action": "scroll_to_top"}\n'
    '{"action": "next_page"}\n'
    '{"action": "input_text", "index": N, "text": "<value>"}\n'
    '{"action": "send_keys", "keys": "Enter"}\n'
    '{"action": "go_back"}\n'
    '{"action": "at_form"}  -- you are ON the application form\n'
    '{"action": "stuck", "reason": "<why blocked>"}\n\n'
    "# Rules\n"
    "- Return at_form if you see application form fields: name, email, phone, file upload for resume/CV\n"
    "- A file input (type=file) for resume is a DEFINITIVE signal — return at_form immediately\n"
    "- Do NOT return at_form for login-only pages\n"
    "- Avoid URLs/actions already in navigation history\n"
    "- Use scroll_to_bottom or next_page if the page might have more links below\n"
    "- Return stuck only as last resort\n"
    "- Return up to 2 actions maximum\n"
    "- Return ONLY valid JSON, no prose, no markdown"
)

FILL_SYSTEM_PROMPT = (
    "You fill job application form fields from the applicant's profile and CV.\n\n"
    "Interactive elements are listed as: [index]<type attributes>text</>\n"
    "Use the numeric index to reference each element.\n\n"
    "Return a JSON array of fill commands:\n"
    '  {"index": N, "value": "<value>", "action": "input_text", "uncertain": false}\n'
    '  {"index": N, "action": "select_option", "text": "<option text>", "uncertain": false}\n'
    '  {"index": N, "value": "__CV__", "action": "file_upload"}  -- for CV/resume file input\n'
    '  {"index": N, "value": "__COVER_LETTER__", "action": "file_upload"}  -- for cover letter\n\n'
    "Rules:\n"
    "- NEVER fill authentication/login fields\n"
    "- uncertain=true if you are not sure of the correct value\n"
    "- Omit fields you have no data for\n"
    "- For select dropdowns, use exact option text\n"
    "- Return ONLY the JSON array, no prose\n"
)

CORRECTION_SYSTEM_PROMPT = (
    "Correct job application fill commands based on user feedback. "
    "Commands use 'index' (int) to reference form elements. "
    "Return the corrected JSON array only."
)
```

- [ ] **Step 2: Verify it imports without error**

```bash
cd backend && uv run python -c "from backend.tailorer.llm import large_llm, NAV_SYSTEM_PROMPT, FILL_SYSTEM_PROMPT, CORRECTION_SYSTEM_PROMPT; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/llm.py
git commit -m "feat(tailorer): extract LLM factory + prompt constants to llm.py"
```

---

### Task 2: Create `navigation.py`

**Files:**
- Create: `backend/backend/tailorer/navigation.py`

- [ ] **Step 1: Create the file**

```python
import json
import logging
import re
from urllib.parse import urljoin

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from backend.tailorer.llm import large_llm, NAV_SYSTEM_PROMPT
from backend.tailorer.state import TailorerState

_log = logging.getLogger(__name__)

_MAX_NAV_STEPS = 10
_STUCK_NUDGE_THRESHOLD = 2
_STUCK_USER_THRESHOLD = 4
_STUCK_HINT = (
    "Your previous action(s) did not change the page (same URL and elements). "
    "Do NOT repeat the last action — try a DIFFERENT element, scroll, or go_to_url."
)


def _resolve_url(href: str, base_url: str) -> str:
    return urljoin(base_url, href)


def _next_no_progress(prev_snapshot: dict | None, new_snapshot, prior_count: int) -> int:
    prev = prev_snapshot or {}
    new = new_snapshot if isinstance(new_snapshot, dict) else {}
    unchanged = new.get("url") == prev.get("url") and new.get("elements") == prev.get("elements")
    return prior_count + 1 if unchanged else 0


def _decide_next_navigation(
    llm,
    snapshot: dict,
    job_title: str,
    nav_history: list,
    nav_memory: str,
    stuck_hint: str = "",
) -> dict:
    elements = snapshot.get("elements", "")
    current_url = snapshot.get("url", "")
    scroll_y = snapshot.get("scroll_y", 0)
    scroll_height = snapshot.get("scroll_height", 0)
    viewport_height = snapshot.get("viewport_height", 800)
    history_str = " → ".join(nav_history[-8:]) if nav_history else "none"
    can_scroll_down = scroll_y + viewport_height < scroll_height - 50
    hint_str = f"\n\n⚠ {stuck_hint}" if stuck_hint else ""

    _log.info("[_decide_next_navigation] url=%s scroll=%d/%d", current_url, scroll_y, scroll_height)

    resp = llm.invoke([
        SystemMessage(content=NAV_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Goal: find and open the application form for: \"{job_title}\"\n"
            f"Current URL: {current_url}\n"
            f"Navigation history: {history_str}\n"
            f"Memory: {nav_memory or 'none'}\n"
            f"Can scroll down: {can_scroll_down}\n\n"
            f"Interactive elements:\n{elements}"
            f"{hint_str}"
        )),
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    _log.info("[_decide_next_navigation] raw=%s", raw)
    return json.loads(raw)


def navigate_to_apply(state: TailorerState) -> TailorerState:
    """
    ReAct loop: observe → think → act until the application form is found.
    Two phases per LangGraph iteration (avoids double LLM call on replay):
      deciding  → LLM picks action, no interrupt, stores in nav_action
      executing → executes nav_action with one interrupt, back to deciding
    """
    llm = large_llm()
    phase = state.get("nav_phase") or "start"
    snapshot = state.get("nav_snapshot")
    nav_steps = state.get("retry_count", 0)
    nav_history = list(state.get("nav_history") or [])

    _log.info(
        "[navigate_to_apply] phase=%s steps=%d url=%s",
        phase, nav_steps, snapshot.get("url") if snapshot else None,
    )

    if phase == "start":
        snap = interrupt({"type": "navigate", "url": state["company_homepage"]})
        return {
            **state,
            "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
            "nav_history": [state["company_homepage"]], "retry_count": 0,
            "nav_memory": "", "no_progress_count": 0,
        }

    if phase == "snapshot":
        snap = interrupt({"type": "request_snapshot"})
        return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None}

    if phase == "deciding":
        no_progress = state.get("no_progress_count", 0)

        if nav_steps >= _MAX_NAV_STEPS:
            return {**state, "nav_phase": "executing", "nav_action": {
                "current_state": {},
                "action": [{"action": "stuck", "reason": "Reached maximum navigation steps."}],
            }}

        if no_progress >= _STUCK_USER_THRESHOLD:
            current_url = (snapshot or {}).get("url", "")
            return {**state, "nav_phase": "executing", "nav_action": {
                "current_state": {},
                "action": [{"action": "stuck", "reason": f"Stuck — no progress at {current_url}."}],
            }}

        stuck_hint = _STUCK_HINT if no_progress >= _STUCK_NUDGE_THRESHOLD else ""
        try:
            decision = _decide_next_navigation(
                llm, snapshot, state["job_title"], nav_history,
                state.get("nav_memory") or "", stuck_hint=stuck_hint,
            )
        except Exception as e:
            _log.warning("[navigate_to_apply] LLM failed: %s", e)
            decision = {"current_state": {}, "action": [{"action": "stuck", "reason": f"LLM error: {e}"}]}

        memory = (decision.get("current_state") or {}).get("memory", "")
        _log.info("[navigate_to_apply] decision=%s memory=%s", decision, memory)
        return {**state, "nav_phase": "executing", "nav_action": decision, "nav_memory": memory}

    if phase == "executing":
        actions = state.get("nav_action") or {}
        action_list = actions.get("action") or []
        if not action_list:
            return {**state, "nav_phase": "nav_done", "apply_url": (snapshot or {}).get("url", ""), "status": "tailoring"}

        first_action = action_list[0]
        act = first_action.get("action")

        if act == "at_form":
            _log.info("[navigate_to_apply] at_form url=%s", (snapshot or {}).get("url"))
            return {**state, "nav_phase": "nav_done", "apply_url": (snapshot or {}).get("url", ""), "status": "tailoring"}

        if act == "stuck":
            reason = first_action.get("reason", "Unable to proceed.")
            interrupt({"type": "show_stuck", "message": f"{reason} Please navigate to the application form."})
            return {**state, "nav_phase": "snapshot", "nav_snapshot": None, "nav_action": None, "retry_count": 0, "no_progress_count": 0}

        if act == "go_to_url":
            url = _resolve_url(first_action.get("url", ""), (snapshot or {}).get("url", ""))
            snap = interrupt({"type": "execute_actions", "actions": action_list})
            return {
                **state,
                "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                "nav_history": nav_history + [url], "retry_count": nav_steps + 1,
                "no_progress_count": _next_no_progress(snapshot, snap, state.get("no_progress_count", 0)),
            }

        current_url = (snapshot or {}).get("url", "")
        snap = interrupt({"type": "execute_actions", "actions": action_list})
        url_after = snap.get("url", current_url) if isinstance(snap, dict) else current_url
        return {
            **state,
            "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
            "nav_history": nav_history + [url_after], "retry_count": nav_steps + 1,
            "no_progress_count": _next_no_progress(snapshot, snap, state.get("no_progress_count", 0)),
        }

    return {**state, "nav_phase": "nav_done", "status": "tailoring"}
```

- [ ] **Step 2: Verify it imports without error**

```bash
cd backend && GROQ_API_KEY=x GROQ_MODEL_LARGE=x uv run python -c "from backend.tailorer.navigation import navigate_to_apply, _decide_next_navigation, _MAX_NAV_STEPS; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/navigation.py
git commit -m "feat(tailorer): extract navigation node + helpers to navigation.py"
```

---

### Task 3: Create `form.py`

**Files:**
- Create: `backend/backend/tailorer/form.py`

- [ ] **Step 1: Create the file**

```python
import io
import json
import logging
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from backend.tailorer.llm import large_llm, FILL_SYSTEM_PROMPT, CORRECTION_SYSTEM_PROMPT
from backend.tailorer.state import TailorerState

_log = logging.getLogger(__name__)

_COMPLETION_KEYWORDS = [
    "thank you", "application received", "successfully submitted",
    "you've applied", "you have applied", "congratulations",
    "application complete", "we'll be in touch",
]


def _map_fields(llm, snapshot: dict, state: TailorerState) -> list[dict]:
    profile_str = json.dumps(state["profile"], indent=2)
    elements = snapshot.get("elements", "")
    resp = llm.invoke([
        SystemMessage(content=FILL_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Profile:\n{profile_str}\n\n"
            f"CV (excerpt):\n{state['cv_text'][:1500]}\n\n"
            f"Cover letter:\n{state['cl_text'][:400]}\n\n"
            f"Interactive elements:\n{elements}"
        )),
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def _apply_correction(llm, correction_text: str, original_commands: list[dict], state: TailorerState) -> list[dict]:
    resp = llm.invoke([
        SystemMessage(content=CORRECTION_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Original commands:\n{json.dumps(original_commands, indent=2)}\n\n"
            f"User correction: {correction_text}\n\n"
            f"Profile:\n{json.dumps(state['profile'], indent=2)}"
        )),
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def confirm_apply(state: TailorerState) -> TailorerState:
    fields = state.get("nav_snapshot", {}) or {}
    field_list = ", ".join(
        f"{f.get('label') or f.get('id')} ({f.get('type')})"
        for f in (fields.get("fields") or [])[:8]
    ) or "various fields"
    interrupt({
        "type": "show_confirm",
        "summary": (
            f"I've reached the application form for '{state['job_title']}'. "
            f"Fields visible: {field_list}. "
            f"Shall I tailor your CV and start filling it out?"
        ),
        "uncertain_fields": [],
    })
    return state


async def tailor_documents(state: TailorerState) -> TailorerState:
    from groq import AsyncGroq
    from backend.tailorer.tailor import generate_tailored_documents

    groq_client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])

    if not state["cv_bytes"]:
        import docx as _docx
        doc = _docx.Document()
        for line in (state["cv_text"] or "").split("\n"):
            doc.add_paragraph(line)
        buf = io.BytesIO()
        doc.save(buf)
        cv_bytes = buf.getvalue()
    else:
        cv_bytes = state["cv_bytes"]

    tailored_cv, cl_bytes, cl_text = await generate_tailored_documents(
        cv_text=state["cv_text"],
        cv_bytes=cv_bytes,
        job_description=state["job_description"],
        groq_client=groq_client,
    )
    return {**state, "cv_bytes": tailored_cv, "cl_bytes": cl_bytes, "cl_text": cl_text, "status": "filling"}


def fetch_snapshot(state: TailorerState) -> TailorerState:
    snapshot = interrupt({"type": "request_snapshot"})
    return {**state, "last_snapshot": snapshot}


def fill_page(state: TailorerState) -> TailorerState:
    llm = large_llm()
    snapshot = state["last_snapshot"]
    elements = (snapshot or {}).get("elements", "")
    _log.info("[fill_page] url=%s elements_len=%d", (snapshot or {}).get("url", "?"), len(elements))

    if not elements:
        page_text = (snapshot or {}).get("page_text", "").lower()
        title = (snapshot or {}).get("title", "").lower()
        if any(kw in page_text or kw in title for kw in _COMPLETION_KEYWORDS):
            _log.info("[fill_page] completion page detected")
            return {**state, "status": "done"}
        _log.info("[fill_page] no elements, treating as completion")
        return {**state, "status": "done"}

    already_filled = state.get("filled_fields") or {}
    all_commands = _map_fields(llm, snapshot, state)
    _log.info("[fill_page] _map_fields returned %d commands", len(all_commands))

    commands = [c for c in all_commands if str(c.get("index")) not in already_filled]

    if state["pending_correction"]:
        commands = _apply_correction(llm, state["pending_correction"], commands, state)

    confirm_commands = [
        c for c in commands
        if c.get("uncertain") or c.get("action") == "file_upload"
        or c.get("value") in ("__CV__", "__COVER_LETTER__")
    ]

    page_label = f"page {state['current_page'] + 1}"
    response = interrupt({
        "type": "fill_and_confirm",
        "commands": commands,
        "confirm_commands": confirm_commands,
        "summary": f"Filling {page_label} — check uncertain fields below",
        "uncertain_fields": [str(c["index"]) for c in commands if c.get("uncertain")],
    })

    rtype = (response or {}).get("type")
    if rtype == "user_approved":
        updated_fields = {
            **already_filled,
            **{str(c.get("index", "")): c.get("value", "") for c in commands},
        }
        return {**state, "filled_fields": updated_fields, "last_snapshot": None, "pending_correction": None, "status": "navigating"}
    if rtype == "user_correction":
        return {**state, "pending_correction": response["text"], "status": "filling_correction"}
    if rtype == "user_manual_edit":
        updated_fields = {**already_filled, str(response.get("index", "")): response.get("value", "")}
        return {**state, "filled_fields": updated_fields, "pending_correction": None, "status": "filling_correction"}
    return {**state, "status": "failed"}


def navigate_next(state: TailorerState) -> TailorerState:
    interrupt({"type": "navigate_next"})
    return {**state, "current_page": state["current_page"] + 1, "last_snapshot": None, "status": "filling"}


async def node_done(state: TailorerState) -> TailorerState:
    return {**state, "status": "done"}
```

- [ ] **Step 2: Verify it imports without error**

```bash
cd backend && GROQ_API_KEY=x GROQ_MODEL_LARGE=x uv run python -c "from backend.tailorer.form import fill_page, fetch_snapshot, navigate_next, node_done, confirm_apply, tailor_documents; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/form.py
git commit -m "feat(tailorer): extract form nodes + helpers to form.py"
```

---

### Task 4: Update `agent.py` imports

**Files:**
- Modify: `backend/backend/tailorer/agent.py`

- [ ] **Step 1: Replace the import block**

Replace lines 6–15 of `agent.py`:

```python
from backend.tailorer.navigation import navigate_to_apply
from backend.tailorer.form import (
    confirm_apply,
    tailor_documents,
    fetch_snapshot,
    fill_page,
    navigate_next,
    node_done,
)
```

- [ ] **Step 2: Verify the graph still builds**

```bash
cd backend && GROQ_API_KEY=x GROQ_MODEL_LARGE=x uv run python -c "
from unittest.mock import MagicMock
from backend.tailorer.agent import build_graph
g = build_graph(MagicMock())
print('nodes:', list(g.nodes))
"
```

Expected: prints node names including `navigate_to_apply`, `fill_page`, etc.

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/agent.py
git commit -m "refactor(tailorer): update agent.py imports to navigation + form modules"
```

---

### Task 5: Refactor `router.py` interrupt dispatch

**Files:**
- Modify: `backend/backend/tailorer/router.py`

- [ ] **Step 1: Replace the `_handle_interrupt` function**

Find `_handle_interrupt` (lines 76–138) and replace it entirely with the dispatch map below.
Also add `from typing import Any, Callable` to the imports at the top of the file.

```python
from typing import Any, Callable
```

Replace the entire `_handle_interrupt` function with:

```python
async def _handle_navigate(ws: WebSocket, val: dict, **_kw: Any) -> dict:
    await ws.send_json({"type": "navigate", "url": val["url"]})
    return await ws.receive_json()


async def _handle_request_snapshot(ws: WebSocket, _val: dict, **_kw: Any) -> dict:
    await ws.send_json({"type": "request_snapshot"})
    return await ws.receive_json()


async def _handle_execute_actions(ws: WebSocket, val: dict, **_kw: Any) -> dict:
    await ws.send_json({"type": "execute_actions", "actions": val.get("actions", [])})
    return await ws.receive_json()


async def _handle_fill_and_confirm(
    ws: WebSocket, val: dict, thread_id: str = "", token: str = "", **_kw: Any
) -> dict:
    all_cmds = val.get("commands", [])
    confirm_cmds = val.get("confirm_commands", all_cmds)

    file_cmds = [
        c for c in confirm_cmds
        if c.get("action") == "file_upload" or c.get("value") in ("__CV__", "__COVER_LETTER__")
    ]
    regular_cmds = [
        c for c in all_cmds
        if c.get("action") != "file_upload" and c.get("value") not in ("__CV__", "__COVER_LETTER__")
    ]

    for cmd in regular_cmds:
        await ws.send_json(cmd)

    file_links = [
        {
            "field_id": fc["index"],
            "label": "tailored_cv.docx" if fc.get("value") == "__CV__" else "cover_letter.docx",
            "url": (
                f"{_API_BASE}/tailorer/files/{thread_id}/"
                f"{'cv' if fc.get('value') == '__CV__' else 'cover_letter'}"
                f"?token={quote(token)}"
            ),
        }
        for fc in file_cmds
    ]
    uncertain = [f'[{c["index"]}]' for c in confirm_cmds if c.get("uncertain")]

    await ws.send_json({
        "type": "show_confirm",
        "summary": val.get("summary", ""),
        "uncertain_fields": uncertain,
        "file_links": file_links,
    })
    response = await ws.receive_json()

    if response.get("type") == "user_approved":
        for cmd in file_cmds:
            await ws.send_json(cmd)

    return response


async def _handle_show_confirm(ws: WebSocket, val: dict, **_kw: Any) -> dict:
    await ws.send_json(val)
    return await ws.receive_json()


async def _handle_navigate_next(ws: WebSocket, _val: dict, **_kw: Any) -> dict:
    await ws.send_json({"type": "navigate_next"})
    return await ws.receive_json()


async def _handle_show_stuck(ws: WebSocket, val: dict, **_kw: Any) -> dict:
    await ws.send_json({"type": "show_stuck", "message": val["message"]})
    return await ws.receive_json()


_INTERRUPT_HANDLERS: dict[str, Callable[..., Any]] = {
    "navigate":          _handle_navigate,
    "request_snapshot":  _handle_request_snapshot,
    "execute_actions":   _handle_execute_actions,
    "fill_and_confirm":  _handle_fill_and_confirm,
    "show_confirm":      _handle_show_confirm,
    "navigate_next":     _handle_navigate_next,
    "show_stuck":        _handle_show_stuck,
}


async def _handle_interrupt(
    ws: WebSocket, interrupt_val: dict, thread_id: str = "", token: str = ""
) -> dict:
    handler = _INTERRUPT_HANDLERS.get(interrupt_val.get("type", ""))
    if not handler:
        return {"type": "unknown"}
    return await handler(ws, interrupt_val, thread_id=thread_id, token=token)
```

- [ ] **Step 2: Verify the router imports without error**

```bash
cd backend && GROQ_API_KEY=x GROQ_MODEL_LARGE=x uv run python -c "from backend.tailorer.router import router; print('routes:', [r.path for r in router.routes])"
```

Expected: prints routes including `/tailorer/ws/{job_id}`

- [ ] **Step 3: Commit**

```bash
git add backend/backend/tailorer/router.py
git commit -m "refactor(tailorer): replace _handle_interrupt if/elif with dispatch map"
```

---

### Task 6: Update tests and delete `nodes.py`

**Files:**
- Modify: `backend/tests/tailorer/test_nodes.py`
- Delete: `backend/backend/tailorer/nodes.py`

- [ ] **Step 1: Replace `test_nodes.py` with updated imports**

The tests currently import `backend.tailorer.nodes`. All references must change:
- `navigate_to_apply`, `_decide_next_navigation`, `_next_no_progress`, `_MAX_NAV_STEPS`, `_STUCK_NUDGE_THRESHOLD`, `_STUCK_USER_THRESHOLD`, `interrupt` → `backend.tailorer.navigation`
- `_map_fields_sync` (renamed `_map_fields`), `fill_page`, `interrupt` → `backend.tailorer.form`
- Patches on `backend.tailorer.nodes.ChatOpenAI` → `backend.tailorer.llm.ChatOpenAI`

Full replacement of `backend/tests/tailorer/test_nodes.py`:

```python
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
```

- [ ] **Step 2: Run the updated tests — they should all pass**

```bash
cd backend && uv run pytest tests/tailorer/test_nodes.py -v
```

Expected: all tests pass (same count as before).

- [ ] **Step 3: Delete `nodes.py`**

```bash
rm backend/backend/tailorer/nodes.py
```

- [ ] **Step 4: Run the full backend test suite to confirm nothing broke**

```bash
cd backend && uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/tailorer/test_nodes.py
git add -u backend/backend/tailorer/nodes.py
git commit -m "refactor(tailorer): update tests to navigation/form modules, delete nodes.py"
```
