import io
import json
import logging
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from backend.tailorer.llm import large_llm, FILL_SYSTEM_PROMPT
from backend.tailorer.state import TailorerState
from backend.tailorer.tailor import generate_tailored_documents

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


# ---------------------------------------------------------------------------
# Compatibility stubs — agent.py (Task 4) still imports these names.
# They will be removed when agent.py is rewritten in Task 4.
# ---------------------------------------------------------------------------

def confirm_apply(state: TailorerState) -> TailorerState:
    """Stub: replaced by node_map / node_apply in Task 4."""
    raise NotImplementedError("confirm_apply removed; use node_map + node_apply")


async def tailor_documents(state: TailorerState) -> TailorerState:
    """Stub: document generation moved into node_map."""
    raise NotImplementedError("tailor_documents removed; generation happens in node_map")


def fetch_snapshot(state: TailorerState) -> TailorerState:
    """Stub: snapshot is now passed in with start_or_fill, not fetched as a separate node."""
    raise NotImplementedError("fetch_snapshot removed; snapshot passed via interrupt payload")


def fill_page(state: TailorerState) -> TailorerState:
    """Stub: replaced by node_map + node_apply."""
    raise NotImplementedError("fill_page removed; use node_map + node_apply")


def navigate_next(state: TailorerState) -> TailorerState:
    """Stub: multi-page navigation removed from fill flow."""
    raise NotImplementedError("navigate_next removed in fill-redesign")


async def node_done(state: TailorerState) -> TailorerState:
    return {**state, "status": "done"}


# ---------------------------------------------------------------------------


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
