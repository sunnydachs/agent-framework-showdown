"""Smoke test for FileCheckpointSaver: put -> get_tuple -> resume across save."""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from langgraph.checkpoint.base import EmptyChannelError  # noqa: F401
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from ckpt_file import FileCheckpointSaver

DB = "/tmp/ckpt_smoke"
shutil.rmtree(DB, ignore_errors=True)


class St(dict):
    pass


def build():
    from typing import TypedDict

    class S(TypedDict):
        x: str
        hit: bool

    def node_a(state):
        return {"x": state["x"] + "-a"}

    def gate(state):
        decision = interrupt({"q": "go?"})
        return {"hit": decision == "yes"}

    def node_c(state):
        return {"x": state["x"] + "-c"}

    g = StateGraph(S)
    g.add_node("a", node_a)
    g.add_node("gate", gate)
    g.add_node("c", node_c)
    g.set_entry_point("a")
    g.add_edge("a", "gate")
    g.add_conditional_edges("gate", lambda s: "c" if s["hit"] else END, {"c": "c", "end": END})
    g.add_edge("c", END)
    return g


saver = FileCheckpointSaver(DB)
graph = build().compile(checkpointer=saver)
cfg = {"configurable": {"thread_id": "t1"}}

# Phase 1: run to the interrupt
for _ in graph.stream({"x": "v"}, cfg, stream_mode="updates"):
    pass
snap = graph.get_state(cfg)
assert snap.next, f"FAIL: expected interrupt, next={snap.next}"
print("phase1: interrupted at", snap.next)

# Phase 2: resume (same process, simulates survival)
for _ in graph.stream(Command(resume="yes"), cfg, stream_mode="updates"):
    pass
snap2 = graph.get_state(cfg)
assert snap2.values.get("x") == "v-a-c", snap2.values
print("phase2: resumed, x =", snap2.values.get("x"))

# Phase 3: NEW saver instance (simulates a NEW process reading the same files)
saver2 = FileCheckpointSaver(DB)
graph2 = build().compile(checkpointer=saver2)
cfg2 = {"configurable": {"thread_id": "t1"}}
snap3 = graph2.get_state(cfg2)
print("phase3 (new process view): next =", snap3.next, "values =", dict(snap3.values))
assert snap3.values.get("x") == "v-a-c", "FAIL: state did not survive"
assert not snap3.next, "FAIL: completed thread shows pending next"
print("SMOKE OK: durable file checkpointer survives process recreation")
