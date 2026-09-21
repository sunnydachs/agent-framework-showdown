"""LangGraph: framework-level HITL with interrupt() (D experiment).

THE enterprise pattern: interrupt() + checkpointer. The graph suspends at the
approval node, the "human" decides, the graph resumes with Command(resume=...).
No re-execution of previous nodes on resume - that's what the checkpointer buys.

Whether the suspension actually fires, what state it saves, and what the
resume costs (tokens, calls) are what the traces show.

Run: RUN_LABEL=langgraph__hitl_approve_run1 APPROVAL_MODE=approve \
     OPENAI_BASE_URL=http://127.0.0.1:8118/v1 MODEL=<model> \
     .venv-langgraph/bin/python frameworks/langgraph_hitl.py
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines  # noqa: E402
from tools_hitl import publish  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "approve")
MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")

llm = ChatOpenAI(
    model=MODEL,
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    default_headers={"X-Run-Label": RUN_LABEL},
)


class HitlState(TypedDict):
    headlines: list
    draft: str
    approved: bool
    published: bool


def write_draft(state: HitlState) -> dict:
    data = fetch_headlines("AI agents", 5)
    joined = "\n".join(f"- {h}" for h in data["headlines"])
    prompt = (
        "Write a tech news digest of about 100 words based on these headlines.\n"
        f"Output the digest text only.\n\nHeadlines:\n{joined}"
    )
    resp = llm.invoke(prompt)
    return {"draft": resp.content, "headlines": data["headlines"]}


def approval_gate(state: HitlState) -> dict:
    # THE HARD STATE BREAK - the graph suspends HERE. The interrupt payload is
    # what the reviewer sees. Command(resume=...) returns the decision.
    decision = interrupt({
        "request": "Approve publishing this digest?",
        "draft": state["draft"],
        "reviewer": "scripted-reviewer",
    })
    return {"approved": bool(decision.get("approved", False)) if isinstance(decision, dict) else bool(decision)}


def publish_node(state: HitlState) -> dict:
    # Only reachable when approved=true (the edge condition enforces it)
    if not state["approved"]:
        return {"published": False}
    out = publish(state["draft"])
    return {"published": out["status"] == "published"}


def after_approval(state: HitlState) -> str:
    return "publish" if state["approved"] else "end"


workflow = StateGraph(HitlState)
workflow.add_node("write", write_draft)
workflow.add_node("approve", approval_gate)
workflow.add_node("publish", publish_node)

workflow.set_entry_point("write")
workflow.add_edge("write", "approve")
workflow.add_conditional_edges("approve", after_approval, {"publish": "publish", "end": END})
workflow.add_edge("publish", END)

checkpointer = MemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": RUN_LABEL or "hitl-demo"}}

t0 = time.time()
# Phase 1: run to the interrupt
events = []
final = None
interrupted_payload = None
for ev in graph.stream({"headlines": [], "draft": "", "approved": False, "published": False}, config, stream_mode="updates"):
    events.append(ev)
phase1_elapsed = time.time() - t0

# Detect the interrupt payload
state_snap = graph.get_state(config)
if state_snap.next:
    interrupted_payload = state_snap.tasks[0].interrupts[0].value if state_snap.tasks else None

# Phase 2: the "human" decides and the graph resumes (no re-execution)
t1 = time.time()
decision = {"approved": APPROVAL_MODE == "approve"}
for ev in graph.stream(Command(resume=decision), config, stream_mode="updates"):
    events.append(ev)
phase2_elapsed = time.time() - t1
elapsed = time.time() - t0

final_state = graph.get_state(config).values

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"langgraph_hitl_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "langgraph",
            "task": "hitl",
            "approval_mode": APPROVAL_MODE,
            "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2),
            "phase1_s": round(phase1_elapsed, 2),
            "phase2_resume_s": round(phase2_elapsed, 2),
            "interrupted": state_snap.next is not None,
            "interrupt_payload": str(interrupted_payload)[:200] if interrupted_payload else None,
            "approved": final_state.get("approved"),
            "published": final_state.get("published"),
            "draft_head": (final_state.get("draft") or "")[:200],
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[langgraph-hitl] done in {elapsed:.1f}s (p1 {phase1_elapsed:.1f}s + resume {phase2_elapsed:.1f}s) ({RUN_LABEL})")
print(f"interrupted={state_snap.next is not None} approved={final_state.get('approved')} published={final_state.get('published')}")
