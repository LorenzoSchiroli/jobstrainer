from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.tailorer.state import TailorerState
from backend.tailorer.navigation import navigate_to_apply
from backend.tailorer.form import node_map, node_apply


def _route_after_apply(state: TailorerState) -> str:
    if state["status"] == "applying":
        return "apply"
    return END


def build_graph(checkpointer: AsyncPostgresSaver) -> Any:
    graph = StateGraph(TailorerState)

    graph.add_node("navigate_to_apply", navigate_to_apply)
    graph.add_node("map", node_map)
    graph.add_node("apply", node_apply)

    graph.set_entry_point("navigate_to_apply")
    graph.add_edge("navigate_to_apply", "map")
    graph.add_edge("map", "apply")
    graph.add_conditional_edges("apply", _route_after_apply)

    return graph.compile(checkpointer=checkpointer)
