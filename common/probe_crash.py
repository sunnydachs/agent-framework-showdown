"""Probes for Cell A design: input-checkpoint timing + resume-error shape."""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command
from typing import TypedDict

from ckpt_file import FileCheckpointSaver


class S(TypedDict):
    x: str


def build(crash_in_entry: bool):
    def entry(state):
        if crash_in_entry:
            import os

            os._exit(9)
        return {"x": state["x"] + "-e"}

    g = StateGraph(S)
    g.add_node("entry", entry)
    g.set_entry_point("entry")
    g.add_edge("entry", END)
    return g


# Q1: crash inside the FIRST node - does a durable checkpoint exist after?
# NOTE: stream() is LAZY - the node only runs when iterated. os._exit(9) in a
# node kills the WHOLE process, so this probe run must end here (exit 9); the
# checkpoint-file inspection happens in the driver (runs/run_crash_idem.py).
DB = "/tmp/ckpt_probe_q1"
shutil.rmtree(DB, ignore_errors=True)
saver = FileCheckpointSaver(DB)
graph = build(crash_in_entry=True).compile(checkpointer=saver)
for _ev in graph.stream({"x": "v"}, {"configurable": {"thread_id": "p1"}}, stream_mode="updates"):
    pass  # the node fires os._exit(9) mid-iteration - never reached
print("q1: SURVIVED entry-node os._exit (unexpected)")

# Q2: fresh-process resume attempt with NO checkpoint anywhere
saver3 = MemorySaver()
graph3 = build(crash_in_entry=False).compile(checkpointer=saver3)
cfg3 = {"configurable": {"thread_id": "p3"}}
snap = graph3.get_state(cfg3)
print("q2: get_state on empty MemorySaver -> next =", snap.next, "values =", dict(snap.values))
try:
    for ev in graph3.stream(Command(resume="yes"), cfg3, stream_mode="updates"):
        pass
    print("q2: resume-without-checkpoint SUCCEEDED (no error)")
except Exception as e:
    print("q2: resume-without-checkpoint raised:", type(e).__name__, "|", str(e)[:200])

# Q3: durable saver, resume when checkpoint exists but graph COMPLETED already
DB4 = "/tmp/ckpt_probe_q3"
shutil.rmtree(DB4, ignore_errors=True)
graph4 = build(crash_in_entry=False).compile(checkpointer=FileCheckpointSaver(DB4))
cfg4 = {"configurable": {"thread_id": "p4"}}
for _ in graph4.stream({"x": "v"}, cfg4, stream_mode="updates"):
    pass
try:
    for ev in graph4.stream(Command(resume="yes"), cfg4, stream_mode="updates"):
        pass
    print("q3: resume-after-completion SUCCEEDED (no error)")
except Exception as e:
    print("q3: resume-after-completion raised:", type(e).__name__, "|", str(e)[:160])
