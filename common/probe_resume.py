"""Probe q4: fresh-process resume from the input-only checkpoint left by a crash.

This is the LangGraph issue-8764 shape: the process crashed inside the FIRST
node, so the only durable checkpoint is the input checkpoint (channel_values
= {'__start__': ...}, no node output, no interrupt). A NEW process resumes
the thread with Command(resume=...) - what happens?
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from ckpt_file import FileCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command
from typing import TypedDict


class S(TypedDict):
    x: str


def build():
    def entry(state):
        return {"x": state["x"] + "-e"}

    g = StateGraph(S)
    g.add_node("entry", entry)
    g.set_entry_point("entry")
    g.add_edge("entry", END)
    return g


saver = FileCheckpointSaver("/tmp/ckpt_probe_q1")
graph = build().compile(checkpointer=saver)
cfg = {"configurable": {"thread_id": "p1"}}

snap = graph.get_state(cfg)
print("get_state -> next =", snap.next, "values =", dict(snap.values))
try:
    events = list(graph.stream(Command(resume="yes"), cfg, stream_mode="updates"))
    print("resume SUCCEEDED, events =", events)
except Exception as e:
    print("resume raised:", type(e).__name__, "|", str(e)[:300])

# Also try the fresh-input path (treat the thread as new, not resuming)
cfg_new = {"configurable": {"thread_id": "p1-fresh"}}
try:
    events = list(graph.stream({"x": "v-fresh"}, cfg_new, stream_mode="updates"))
    print("fresh-input SUCCEEDED, events =", events)
except Exception as e:
    print("fresh-input raised:", type(e).__name__, "|", str(e)[:200])
