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


def _find_best_link_in_snapshot(snapshot: dict, keywords: list[str]) -> str | None:
    """Fast keyword match over snapshot links. Returns href or None."""
    for link in snapshot.get("links", []):
        label = (link.get("label") or link.get("text") or "").lower()
        href = link.get("href") or ""
        combined = label + " " + href.lower()
        if any(kw in combined for kw in keywords):
            return href
    return None


def _map_fields_sync(llm, snapshot: dict, state: TailorerState) -> list[dict]:
    SYSTEM = (
        "You fill job application form fields from the applicant's profile and CV.\n\n"
        "Return a JSON array of fill commands, each:\n"
        '  {"field_id":"<id>","value":"<value>","uncertain":false}\n\n'
        "For file upload fields (type=file):\n"
        '  {"field_id":"<id>","value":"__CV__","type":"file"}      <- for CV/resume\n'
        '  {"field_id":"<id>","value":"__COVER_LETTER__","type":"file"}  <- for cover letter\n\n'
        "Rules:\n"
        "- uncertain=true if you are not sure of the correct value\n"
        "- Omit fields you have no data for\n"
        "- For dropdowns, use exact text from the options array\n"
        "- Return ONLY the JSON array, no prose\n"
    )
    profile_str = json.dumps(state["profile"], indent=2)
    fields_str = json.dumps(snapshot.get("fields", []), indent=2)
    resp = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Profile:\n{profile_str}\n\n"
            f"CV (excerpt):\n{state['cv_text'][:3000]}\n\n"
            f"Cover letter:\n{state['cl_text'][:800]}\n\n"
            f"Form fields:\n{fields_str}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def _apply_correction_sync(llm, correction_text: str, original_commands: list[dict], state: TailorerState) -> list[dict]:
    resp = llm.invoke([
        SystemMessage(content="Correct job application fill commands based on user feedback. Return the corrected JSON array only."),
        HumanMessage(content=(
            f"Original commands:\n{json.dumps(original_commands, indent=2)}\n\n"
            f"User correction: {correction_text}\n\n"
            f"Profile:\n{json.dumps(state['profile'], indent=2)}"
        ))
    ])
    raw = re.sub(r"```(?:json)?\s*|\s*```", "", resp.content.strip())
    return json.loads(raw)


def _find_apply_url_in_snapshot(llm, snapshot: dict, job_title: str) -> str | None:
    """Use LLM to find the apply form URL from a snapshot."""
    links = snapshot.get("links", [])
    if not links:
        return None
    links_str = "\n".join(f"- {l.get('label','')}: {l.get('href','')}" for l in links[:40])
    resp = llm.invoke([
        HumanMessage(content=(
            f"Goal: find the URL for applying to '{job_title}' or a general 'Apply Now' / careers link.\n\n"
            f"Links:\n{links_str}\n\n"
            "Return only the URL, or 'none' if no match."
        ))
    ])
    url = resp.content.strip()
    return None if url.lower() == "none" else url


def navigate_to_apply(state: TailorerState) -> TailorerState:
    llm = _make_llm(_BASE())
    retry = state["retry_count"]

    snapshot = interrupt({"type": "navigate", "url": state["company_homepage"]})

    careers_url = _find_best_link_in_snapshot(snapshot, ["career", "job", "hiring", "work with us", "vacancies"])
    if not careers_url:
        retry += 1
        if retry >= 2:
            interrupt({"type": "show_stuck", "message": "Can't find the careers page. Can you navigate there for me?"})
            retry = 0
        return {**state, "retry_count": retry}

    snapshot = interrupt({"type": "navigate", "url": careers_url})

    apply_url = _find_apply_url_in_snapshot(llm, snapshot, state["job_title"])
    if not apply_url:
        retry += 1
        if retry >= 2:
            interrupt({"type": "show_stuck", "message": f"Can't find '{state['job_title']}' on the careers page. Can you click the job for me?"})
            retry = 0
        return {**state, "retry_count": retry}

    snapshot = interrupt({"type": "navigate", "url": apply_url})
    form_url = _find_best_link_in_snapshot(snapshot, ["apply", "application"])
    if form_url:
        snapshot = interrupt({"type": "navigate", "url": form_url})
        apply_url = form_url

    return {**state, "apply_url": apply_url, "status": "tailoring", "retry_count": 0}


async def tailor_documents(state: TailorerState) -> TailorerState:
    from groq import Groq
    from backend.tailorer.tailor import generate_tailored_documents

    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

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


def fill_page(state: TailorerState) -> TailorerState:
    llm = _make_llm(_BASE())

    if state["last_snapshot"] is None:
        snapshot = interrupt({"type": "request_snapshot"})
        state = {**state, "last_snapshot": snapshot}
    else:
        snapshot = state["last_snapshot"]

    commands = _map_fields_sync(llm, snapshot, state)
    if state["pending_correction"]:
        commands = _apply_correction_sync(llm, state["pending_correction"], commands, state)

    uncertain = [c["field_id"] for c in commands if c.get("uncertain")]
    page_label = f"page {state['current_page'] + 1}"

    response = interrupt({
        "type": "fill_and_confirm",
        "commands": commands,
        "summary": f"Filled {len(commands)} fields on {page_label}",
        "uncertain_fields": uncertain,
    })

    if response["type"] == "user_approved":
        updated_fields = {**state["filled_fields"], **{c["field_id"]: c["value"] for c in commands}}
        return {**state, "filled_fields": updated_fields, "last_snapshot": None, "pending_correction": None, "status": "navigating"}
    elif response["type"] == "user_correction":
        return {**state, "pending_correction": response["text"], "status": "filling_correction"}
    elif response["type"] == "user_manual_edit":
        updated_fields = {**state["filled_fields"], response["field_id"]: response["value"]}
        return {**state, "filled_fields": updated_fields, "pending_correction": None, "status": "filling_correction"}
    return state


def navigate_next(state: TailorerState) -> TailorerState:
    response = interrupt({"type": "navigate_next"})

    if response.get("submitted"):
        return {**state, "status": "done"}
    return {**state, "current_page": state["current_page"] + 1, "last_snapshot": None, "status": "filling"}


async def node_done(state: TailorerState) -> TailorerState:
    return {**state, "status": "done"}
