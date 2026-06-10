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
