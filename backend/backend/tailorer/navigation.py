import json
import logging
import re
from urllib.parse import urljoin

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from backend.tailorer.llm import large_llm
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

    # NOTE: NAV_SYSTEM_PROMPT removed in Task 2; this entire function removed in Task 3
    raise NotImplementedError("Navigation prompts removed; see Task 3 for new fill-only design")
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
