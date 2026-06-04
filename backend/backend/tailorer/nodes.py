import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from backend.tailorer.state import TailorerState

_BASE = lambda: os.environ["GROQ_MODEL_BASE"]
_LARGE = lambda: os.environ["GROQ_MODEL_LARGE"]
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _make_llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        api_key=os.environ["GROQ_API_KEY"],
        base_url=_GROQ_BASE_URL,
    )


def _resolve_url(href: str, base_url: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base_url, href)


def _decide_next_navigation(llm, snapshot: dict, job_title: str, nav_history: list, nav_memory: str) -> dict:
    """Ask LLM what to do next. Returns {current_state: {...}, action: [...]}."""
    elements = snapshot.get("elements", "")
    current_url = snapshot.get("url", "")
    scroll_y = snapshot.get("scroll_y", 0)
    scroll_height = snapshot.get("scroll_height", 0)
    viewport_height = snapshot.get("viewport_height", 800)
    history_str = " → ".join(nav_history[-8:]) if nav_history else "none"
    can_scroll_down = scroll_y + viewport_height < scroll_height - 50

    _log.info("[_decide_next_navigation] url=%s scroll=%d/%d", current_url, scroll_y, scroll_height)

    resp = llm.invoke([
        SystemMessage(content=(
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
        )),
        HumanMessage(content=(
            f"Goal: find and open the application form for: \"{job_title}\"\n"
            f"Current URL: {current_url}\n"
            f"Navigation history: {history_str}\n"
            f"Memory: {nav_memory or 'none'}\n"
            f"Can scroll down: {can_scroll_down}\n\n"
            f"Interactive elements:\n{elements}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    _log.info("[_decide_next_navigation] raw=%s", raw)
    return json.loads(raw)


def _map_fields_sync(llm, snapshot: dict, state: TailorerState) -> list[dict]:
    SYSTEM = (
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
    profile_str = json.dumps(state["profile"], indent=2)
    elements = snapshot.get("elements", "")

    resp = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Profile:\n{profile_str}\n\n"
            f"CV (excerpt):\n{state['cv_text'][:1500]}\n\n"
            f"Cover letter:\n{state['cl_text'][:400]}\n\n"
            f"Interactive elements:\n{elements}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def _apply_correction_sync(llm, correction_text: str, original_commands: list[dict], state: TailorerState) -> list[dict]:
    resp = llm.invoke([
        SystemMessage(content="Correct job application fill commands based on user feedback. Commands use 'index' (int) to reference form elements. Return the corrected JSON array only."),
        HumanMessage(content=(
            f"Original commands:\n{json.dumps(original_commands, indent=2)}\n\n"
            f"User correction: {correction_text}\n\n"
            f"Profile:\n{json.dumps(state['profile'], indent=2)}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)



import logging as _logging
_log = _logging.getLogger(__name__)


_MAX_NAV_STEPS = 10


def navigate_to_apply(state: TailorerState) -> TailorerState:
    """
    ReAct loop: observe → think → act, until the application form is found.
    Two phases per iteration (avoids double LLM call on LangGraph replay):
      deciding  → LLM picks action, NO interrupt, stores in nav_action
      executing → executes nav_action with ONE interrupt, back to deciding
    """
    llm = _make_llm(_LARGE())
    phase = state.get("nav_phase") or "start"
    snapshot = state.get("nav_snapshot")
    nav_steps = state.get("retry_count", 0)
    nav_history = list(state.get("nav_history") or [])

    _log.info("[navigate_to_apply] phase=%s steps=%d url=%s", phase, nav_steps, snapshot.get("url") if snapshot else None)

    # ── Start: navigate to company homepage to get first snapshot ──
    if phase == "start":
        snap = interrupt({"type": "navigate", "url": state["company_homepage"]})
        return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                "nav_history": [state["company_homepage"]], "retry_count": 0, "nav_memory": ""}

    # ── After user unblocked: take fresh snapshot ──
    if phase == "snapshot":
        snap = interrupt({"type": "request_snapshot"})
        return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None}

    # ── Think: LLM decides next action (no interrupt here) ──
    if phase == "deciding":
        if nav_steps >= _MAX_NAV_STEPS:
            return {**state, "nav_phase": "executing",
                    "nav_action": {"current_state": {}, "action": [{"action": "stuck", "reason": "Reached maximum navigation steps."}]}}

        current_url = (snapshot or {}).get("url", "")
        if nav_history.count(current_url) >= 2:
            return {**state, "nav_phase": "executing",
                    "nav_action": {"current_state": {}, "action": [{"action": "stuck", "reason": f"Stuck in loop at {current_url}"}]}}

        try:
            decision = _decide_next_navigation(llm, snapshot, state["job_title"], nav_history, state.get("nav_memory") or "")
        except Exception as e:
            _log.warning("[navigate_to_apply] LLM failed: %s", e)
            decision = {"current_state": {}, "action": [{"action": "stuck", "reason": f"LLM error: {e}"}]}

        memory = (decision.get("current_state") or {}).get("memory", "")
        _log.info("[navigate_to_apply] decision=%s memory=%s", decision, memory)
        return {**state, "nav_phase": "executing", "nav_action": decision, "nav_memory": memory}

    # ── Act: execute the decided action with one interrupt ──
    if phase == "executing":
        actions = state.get("nav_action") or {}
        action_list = actions.get("action") or []
        if not action_list:
            return {**state, "nav_phase": "nav_done", "apply_url": (snapshot or {}).get("url", ""), "status": "tailoring"}

        first_action = action_list[0] if action_list else {}
        act = first_action.get("action")

        if act == "at_form":
            _log.info("[navigate_to_apply] at_form url=%s", (snapshot or {}).get("url"))
            return {**state, "nav_phase": "nav_done", "apply_url": (snapshot or {}).get("url", ""), "status": "tailoring"}

        if act == "stuck":
            reason = first_action.get("reason", "Unable to proceed.")
            interrupt({"type": "show_stuck", "message": f"{reason} Please navigate to the application form."})
            return {**state, "nav_phase": "snapshot", "nav_snapshot": None, "nav_action": None, "retry_count": 0}

        if act == "go_to_url":
            url = _resolve_url(first_action.get("url", ""), (snapshot or {}).get("url", ""))
            snap = interrupt({"type": "execute_actions", "actions": action_list})
            return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                    "nav_history": nav_history + [url], "retry_count": nav_steps + 1}

        # For all other actions (click_element, scroll, input_text, etc.)
        current_url = (snapshot or {}).get("url", "")
        snap = interrupt({"type": "execute_actions", "actions": action_list})
        url_after = snap.get("url", current_url) if isinstance(snap, dict) else current_url
        return {**state, "nav_phase": "deciding", "nav_snapshot": snap, "nav_action": None,
                "nav_history": nav_history + [url_after], "retry_count": nav_steps + 1}

    return {**state, "nav_phase": "nav_done", "status": "tailoring"}


def confirm_apply(state: TailorerState) -> TailorerState:
    fields = state.get("nav_snapshot", {}) or {}
    field_list = ", ".join(
        f"{f.get('label') or f.get('id')} ({f.get('type')})"
        for f in (fields.get("fields") or [])[:8]
    ) or "various fields"
    response = interrupt({
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
        import io
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


_COMPLETION_KEYWORDS = ["thank you", "application received", "successfully submitted", "you've applied", "you have applied", "congratulations", "application complete", "we'll be in touch"]


def fill_page(state: TailorerState) -> TailorerState:
    llm = _make_llm(_LARGE())
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
    all_commands = _map_fields_sync(llm, snapshot, state)
    _log.info("[fill_page] _map_fields_sync returned %d commands", len(all_commands))

    commands = [c for c in all_commands if str(c.get("index")) not in already_filled]

    if state["pending_correction"]:
        commands = _apply_correction_sync(llm, state["pending_correction"], commands, state)

    # Only uncertain fields and file uploads are surfaced to the user
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
        updated_fields = {**already_filled, **{str(c.get("index", "")): c.get("value", "") for c in commands}}
        return {**state, "filled_fields": updated_fields, "last_snapshot": None, "pending_correction": None, "status": "navigating"}
    elif rtype == "user_correction":
        return {**state, "pending_correction": response["text"], "status": "filling_correction"}
    elif rtype == "user_manual_edit":
        updated_fields = {**already_filled, str(response.get("index", "")): response.get("value", "")}
        return {**state, "filled_fields": updated_fields, "pending_correction": None, "status": "filling_correction"}
    return {**state, "status": "failed"}


def navigate_next(state: TailorerState) -> TailorerState:
    interrupt({"type": "navigate_next"})
    # Never trust "submitted" from the extension — completion is detected by fill_page via page content
    return {**state, "current_page": state["current_page"] + 1, "last_snapshot": None, "status": "filling"}


async def node_done(state: TailorerState) -> TailorerState:
    return {**state, "status": "done"}
