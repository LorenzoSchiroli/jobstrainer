from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.tailorer.state import TailorerState
from backend.tailorer.navigation import navigate_to_apply
from backend.tailorer.form import (
    confirm_apply,
    tailor_documents,
    fetch_snapshot,
    fill_page,
    navigate_next,
    node_done,
)


def _route_after_navigate(state: TailorerState) -> str:
    if state.get("nav_phase") == "nav_done":
        return "confirm_apply"
    return "navigate_to_apply"


def _route_after_fill(state: TailorerState) -> str:
    if state["status"] == "done":
        return "done"
    if state["status"] in ("filling", "filling_correction"):
        return "fetch_snapshot"
    return "navigate_next"


def _route_after_navigate_next(state: TailorerState) -> str:
    return "fetch_snapshot"


def build_graph(checkpointer: AsyncPostgresSaver) -> Any:
    graph = StateGraph(TailorerState)

    graph.add_node("navigate_to_apply", navigate_to_apply)
    graph.add_node("confirm_apply", confirm_apply)
    graph.add_node("tailor_documents", tailor_documents)
    graph.add_node("fetch_snapshot", fetch_snapshot)
    graph.add_node("fill_page", fill_page)
    graph.add_node("navigate_next", navigate_next)
    graph.add_node("done", node_done)

    graph.set_entry_point("navigate_to_apply")
    graph.add_conditional_edges("navigate_to_apply", _route_after_navigate)
    graph.add_edge("confirm_apply", "tailor_documents")
    graph.add_edge("tailor_documents", "fetch_snapshot")
    graph.add_edge("fetch_snapshot", "fill_page")
    graph.add_conditional_edges("fill_page", _route_after_fill)
    graph.add_conditional_edges("navigate_next", _route_after_navigate_next)
    graph.add_edge("done", END)

    return graph.compile(checkpointer=checkpointer)
