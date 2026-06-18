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
