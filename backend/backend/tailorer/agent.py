from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.tailorer.state import TailorerState
from backend.tailorer.nodes import (
    navigate_to_apply,
    tailor_documents,
    fill_page,
    navigate_next,
    node_done,
)


def _route_after_fill(state: TailorerState) -> str:
    if state["status"] in ("filling", "filling_correction"):
        return "fill_page"
    return "navigate_next"


def _route_after_navigate_next(state: TailorerState) -> str:
    if state["status"] == "done":
        return "done"
    return "fill_page"


def build_graph(checkpointer: AsyncPostgresSaver) -> Any:
    graph = StateGraph(TailorerState)

    graph.add_node("navigate_to_apply", navigate_to_apply)
    graph.add_node("tailor_documents", tailor_documents)
    graph.add_node("fill_page", fill_page)
    graph.add_node("navigate_next", navigate_next)
    graph.add_node("done", node_done)

    graph.set_entry_point("navigate_to_apply")
    graph.add_edge("navigate_to_apply", "tailor_documents")
    graph.add_edge("tailor_documents", "fill_page")
    graph.add_conditional_edges("fill_page", _route_after_fill)
    graph.add_conditional_edges("navigate_next", _route_after_navigate_next)
    graph.add_edge("done", END)

    return graph.compile(checkpointer=checkpointer)
