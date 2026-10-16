"""Linear LangGraph for market evidence. There is no cycle and no order node."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.analysis.nodes import (
    contrarian_node,
    derivatives_node,
    fusion_node,
    global_context,
    indian_node,
    macro_node,
    news_node,
    report_node,
    validate_node,
)
from app.analysis.state import AnalysisState

_GRAPH = None


def _isolate(name: str, fn):
    """Record a node exception and let the remaining nodes run."""

    def wrapped(state: AnalysisState) -> dict:
        try:
            return fn(state)
        except Exception as exc:
            update = {
                "errors": list(state.get("errors") or []) + [
                    {"node": name, "code": "NODE_FAILED", "message": exc.__class__.__name__}
                ],
                "node_status": {**dict(state.get("node_status") or {}), name: "FAILED"},
                "missing": list(state.get("missing") or []) + [name],
            }
            if name == "validate":
                update["accepted"] = []
                update["rejected"] = list(state.get("rejected") or []) + [
                    {"reason": "Validation failed before observations could be trusted."}
                ]
                update["evidence"] = []
            return update

    return wrapped


def build_graph(overrides: dict | None = None):
    functions = {
        "validate": validate_node,
        "global_context": global_context,
        "news": news_node,
        "macro": macro_node,
        "indian": indian_node,
        "derivatives": derivatives_node,
        "contrarian": contrarian_node,
        "fusion": fusion_node,
        "report": report_node,
    }
    if overrides:
        functions.update(overrides)
    graph = StateGraph(AnalysisState)
    for name, fn in functions.items():
        graph.add_node(name, _isolate(name, fn))
    graph.add_edge(START, "validate")
    graph.add_edge("validate", "global_context")
    graph.add_edge("global_context", "news")
    graph.add_edge("news", "macro")
    graph.add_edge("macro", "indian")
    graph.add_edge("indian", "derivatives")
    graph.add_edge("derivatives", "contrarian")
    graph.add_edge("contrarian", "fusion")
    graph.add_edge("fusion", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=MemorySaver())


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
