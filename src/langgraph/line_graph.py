from __future__ import annotations

"""line_graph.py
Builds a LangGraph StateGraph around an existing ``LineCommander`` instance.
The graph orchestrates **planned** and **reactive** decision-making while
re-using all the proven business logic already present in the commander.  
The goal is to gain a clear, visual, state-machine representation of the
workflow without introducing new behaviour. All MQTT publishing, command
validation and agent reasoning continue to live inside ``LineCommander`` and
``ProductFlowAgent``.

Usage
-----
>>> graph = build_line_graph(line_commander)
>>> await run_line_graph(line_commander, graph)

Nothing in the rest of the codebase needs to change – the commander is still
responsible for side-effects, this wrapper only calls its existing coroutine
methods in the right order.
"""

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed state definition
# ---------------------------------------------------------------------------


class GraphState(TypedDict, total=False):
    """Shared state passed between LangGraph nodes."""

    factory_state: Dict[str, Any]
    # MQTT / factory events waiting for reactive handling
    events: Annotated[List[Dict[str, Any]], add_messages]
    # Optional log entries for debugging / LangSmith traces
    log: Annotated[List[str], add_messages]


# ---------------------------------------------------------------------------
# Graph nodes (implemented as closures so they can capture ``commander``)
# ---------------------------------------------------------------------------


def _build_nodes(commander):  # noqa: C901 – complexity acceptable for one-off
    """Return node callables bound to a *specific* LineCommander instance."""

    async def ingest_node(state: GraphState) -> GraphState:  # type: ignore[override]
        """Pull the latest factory state and any queued events into the graph."""
        new_state: GraphState = {}

        # 1. Snapshot of current factory situation --------------------------
        try:
            new_state["factory_state"] = commander.mqtt_listener.get_factory_state()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Ingest node failed to get factory_state: {exc}")

        # 2. Drain *all* currently queued reactive events -------------------
        drained_events: List[Dict[str, Any]] = []
        while True:
            try:
                event = commander.decision_queue.get_nowait()
                drained_events.append(event)
            except asyncio.QueueEmpty:  # type: ignore[attr-defined]
                break
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Error draining decision_queue: {exc}")
                break

        if drained_events:
            new_state["events"] = drained_events

        # 3. Add debug log entry -------------------------------------------
        new_state["log"] = [
            f"Ingest @ {datetime.now().isoformat()} – events: {len(drained_events)}"
        ]

        return new_state

    # ---------------------------------------------------------------------
    # Decision router – chooses between planned or reactive path
    # ---------------------------------------------------------------------

    def route_node(state: GraphState) -> str:  # type: ignore[override]
        """Return edge label used by conditional routing in LangGraph."""
        if state.get("events"):
            return "reactive_agent"
        return "planned_agent"

    # ---------------------------------------------------------------------
    # Planned operations node ---------------------------------------------
    # ---------------------------------------------------------------------

    async def planned_agent_node(state: GraphState) -> GraphState:  # type: ignore[override]
        """Run the original _process_planned_operations coroutine."""
        await commander._process_planned_operations()  # noqa: SLF001 – internal
        return {"log": [f"Planned agent executed @ {datetime.now().isoformat()}"]}

    # ---------------------------------------------------------------------
    # Reactive operations node --------------------------------------------
    # ---------------------------------------------------------------------

    async def reactive_agent_node(state: GraphState) -> GraphState:  # type: ignore[override]
        """Process the *first* queued event using commander logic."""
        events = state.get("events", [])
        if events:
            event = events[0]
            try:
                await commander._process_reactive_event(event)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Reactive node error: {exc}")
        return {"log": [f"Reactive agent executed @ {datetime.now().isoformat()}"]}

    return ingest_node, route_node, planned_agent_node, reactive_agent_node


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_line_graph(commander):
    """Compile and return a LangGraph for the supplied ``LineCommander``."""
    ingest_node, route_node, planned_agent_node, reactive_agent_node = _build_nodes(
        commander
    )

    graph_builder: StateGraph = StateGraph(GraphState)

    # Register nodes -------------------------------------------------------
    graph_builder.add_node("ingest", ingest_node)
    graph_builder.add_node("route", route_node)
    graph_builder.add_node("planned_agent", planned_agent_node)
    graph_builder.add_node("reactive_agent", reactive_agent_node)

    # Edges / control-flow --------------------------------------------------
    graph_builder.add_edge(START, "ingest")
    graph_builder.add_edge("ingest", "route")

    # Conditional routing based on route_node output
    graph_builder.add_conditional_edges(
        "route",
        {
            "planned_agent": "planned_agent",
            "reactive_agent": "reactive_agent",
        },
    )

    # Both agents converge to END of execution
    graph_builder.add_edge("planned_agent", END)
    graph_builder.add_edge("reactive_agent", END)

    return graph_builder.compile()


async def run_line_graph(commander, graph, poll_interval: float | None = None):
    """Continuously invoke the compiled graph until the commander stops.

    ``poll_interval`` defaults to the commander's reactive_processing_delay so we
    maintain the same responsiveness as before.
    """
    poll = poll_interval if poll_interval is not None else commander.reactive_processing_delay
    logger.info(
        f"LineGraph runner started for {commander.line_id} (interval={poll}s)"
    )

    # Minimal initial state – everything else will be filled by ingest_node
    state: GraphState = {}

    while commander.is_running:
        try:
            # invoke() returns an updated state dict. We *keep* it so that the
            # reducer annotations (e.g. add_messages) accumulate correctly.
            state = await graph.invoke(state)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"LineGraph invocation error: {exc}")

        await asyncio.sleep(poll)

    logger.info(f"LineGraph runner stopped for {commander.line_id}") 