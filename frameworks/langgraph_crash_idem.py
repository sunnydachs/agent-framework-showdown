"""LangGraph crash-resume (Experiment 4, Cell A, LangGraph focus).

PHASE=run      : build the graph (write -> interrupt gate -> publish), run to
                 the interrupt(), print SUSPENDED, then block. The driver
                 SIGKILLs the process while it is suspended mid-interrupt.
PHASE=resume   : a NEW process rebuilds the graph from the durable checkpoint
                 dir + the same thread_id, measures resume latency, resumes
                 with Command(resume=...) and publishes through the gate.
PHASE=resume8764: the issue-8764 shape - a NEW process finds an EMPTY thread
                 (crash before any durable checkpoint: MemorySaver crash or
                 SIGKILL inside the first-checkpoint write window). Attempts
                 Command(resume=...) and invoke(None, ...) and records the raw
                 errors - the failure-record gap.

CRASH_CKPT=mem|durable selects the checkpointer (MemorySaver = the benchmark's
current implementation, everything in-process; durable = FileCheckpointSaver,
every checkpoint survives SIGKILL).

Run (driver): RUN_LABEL=langgraph__crash_durable_run1 PHASE=run \
     CRASH_CKPT=durable OPENAI_BASE_URL=http://127.0.0.1:8118/v1 MODEL=<model> \
     .venv-langgraph/bin/python frameworks/langgraph_crash_idem.py
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

from ckpt_file import FileCheckpointSaver  # noqa: E402

PHASE = os.environ.get("PHASE", "run")
CRASH_CKPT = os.environ.get("CRASH_CKPT", "durable")
MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "approve")
CKPT_DIR = os.environ.get("CKPT_DIR", str(ROOT / "traces" / "ckpt_langgraph"))

llm = ChatOpenAI(
    model=MODEL,
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    default_headers={"X-Run-Label": RUN_LABEL},
)


class CrashState(TypedDict):
    headlines: list
    draft: str
    approved: bool
    published: bool


def write_draft(state: CrashState) -> dict:
    data = fetch_headlines("AI agents", 5)
    joined = "\n".join(f"- {h}" for h in data["headlines"])
    prompt = (
        "Write a tech news digest of about 60 words based on these headlines.\n"
        "Output the digest text only.\n\nHeadlines:\n" + joined
    )
    resp = llm.invoke(prompt)
    return {"draft": resp.content, "headlines": data["headlines"]}


def approval_gate(state: CrashState) -> dict:
    decision = interrupt({"request": "Approve publishing this digest?"})
    return {"approved": bool(decision.get("approved", False)) if isinstance(decision, dict) else bool(decision)}


def publish_node(state: CrashState) -> dict:
    if not state["approved"]:
        return {"published": False}
    out = publish(state["draft"])
    return {"published": out["status"] == "published"}


def after_approval(state: CrashState) -> str:
    return "publish" if state["approved"] else "end"


def build(checkpointer):
    wf = StateGraph(CrashState)
    wf.add_node("write", write_draft)
    wf.add_node("approve", approval_gate)
    wf.add_node("publish", publish_node)
    wf.set_entry_point("write")
    wf.add_edge("write", "approve")
    wf.add_conditional_edges("approve", after_approval, {"publish": "publish", "end": END})
    wf.add_edge("publish", END)
    return wf.compile(checkpointer=checkpointer)


def out_path(tag):
    d = ROOT / "outputs"
    d.mkdir(exist_ok=True)
    return d / f"langgraph_crash_{tag}.json"


def write_out(tag, payload):
    p = out_path(tag)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"[langgraph-crash] wrote {p.name}")


if PHASE == "run":
    checkpointer = MemorySaver() if CRASH_CKPT == "mem" else FileCheckpointSaver(CKPT_DIR)
    graph = build(checkpointer)
    config = {"configurable": {"thread_id": RUN_LABEL or "crash-demo"}}
    t0 = time.time()
    for _ev in graph.stream(
        {"headlines": [], "draft": "", "approved": False, "published": False},
        config,
        stream_mode="updates",
    ):
        pass
    phase1_s = time.time() - t0
    snap = graph.get_state(config)
    interrupted = snap.next is not None and bool(snap.next)
    print(f"SUSPENDED phase1_s={phase1_s:.2f} interrupted={interrupted}", flush=True)
    write_out(f"{RUN_LABEL or 'default'}__phase1", {
        "framework": "langgraph", "phase": "run", "checkpointer": CRASH_CKPT,
        "run_label": RUN_LABEL, "phase1_s": round(phase1_s, 2), "interrupted": interrupted,
    })
    # Block: the driver SIGKILLs here (mid-interrupt). Cap at 120s for safety.
    for _ in range(1200):
        time.sleep(0.1)
    print("NOT KILLED - driver never sent SIGKILL", flush=True)

elif PHASE == "resume":
    checkpointer = MemorySaver() if CRASH_CKPT == "mem" else FileCheckpointSaver(CKPT_DIR)
    graph = build(checkpointer)
    config = {"configurable": {"thread_id": RUN_LABEL or "crash-demo"}}
    snap = graph.get_state(config)
    state_survived = bool(snap.next)  # pending interrupt = the suspension survived
    t0 = time.time()
    if state_survived:
        decision = {"approved": APPROVAL_MODE == "approve"}
        for _ev in graph.stream(Command(resume=decision), config, stream_mode="updates"):
            pass
    resume_s = time.time() - t0
    final = graph.get_state(config).values
    write_out(f"{RUN_LABEL or 'default'}__resume", {
        "framework": "langgraph", "phase": "resume", "checkpointer": CRASH_CKPT,
        "run_label": RUN_LABEL, "state_survived": state_survived,
        "resume_s": round(resume_s, 2), "approved": final.get("approved"),
        "published": final.get("published"),
    })
    print(f"[langgraph-crash] survived={state_survived} resume_s={resume_s:.2f} published={final.get('published')}")

elif PHASE == "resume8764":
    # The issue-8764 shape: EMPTY thread (no durable checkpoint at all).
    # langgraph 1.2.11 empirics: NO EmptyInputError - Command(resume=...) and
    # invoke(None) on the empty thread SILENTLY RE-RUN the graph from scratch
    # (fresh write_draft LLM call each), which is the failure-record gap: the
    # crash left no checkpoint and no error, and the re-run doubles the cost.
    import glob as _glob

    empty_dir = str(ROOT / "traces" / "ckpt_empty_8764")
    results = {"framework": "langgraph", "phase": "resume8764", "shape": "empty thread (crash before any durable checkpoint)"}
    trace_glob = str(ROOT / "traces" / f"llm_calls_*{RUN_LABEL or 'crash_8764'}*.jsonl")
    n_calls_before = sum(1 for f in _glob.glob(trace_glob) for _ in open(f) if f and _.strip())

    # Attempt 1: Command(resume=...) on the empty thread
    graph = build(FileCheckpointSaver(empty_dir))
    config = {"configurable": {"thread_id": "never-ran"}}
    snap = graph.get_state(config)
    results["get_state_next"] = list(snap.next)
    results["get_state_values"] = dict(snap.values)
    try:
        for _ev in graph.stream(Command(resume={"approved": True}), config, stream_mode="updates"):
            pass
        results["command_resume"] = "SUCCEEDED (unexpected)"
    except Exception as e:
        results["command_resume_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # Attempt 2: invoke(None) on the empty thread - the classic EmptyInputError
    try:
        graph.invoke(None, config)
        results["invoke_none"] = "SUCCEEDED (unexpected)"
    except Exception as e:
        results["invoke_none_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    # Attempt 3: MemorySaver variant (what the current benchmark impl loses on crash)
    graph_mem = build(MemorySaver())
    cfg_mem = {"configurable": {"thread_id": "never-ran-mem"}}
    try:
        for _ev in graph_mem.stream(Command(resume={"approved": True}), cfg_mem, stream_mode="updates"):
            pass
        results["mem_command_resume"] = "SUCCEEDED (unexpected)"
    except Exception as e:
        results["mem_command_resume_error"] = f"{type(e).__name__}: {str(e)[:200]}"

    n_calls_after = sum(1 for f in _glob.glob(trace_glob) for _ in open(f) if f and _.strip())
    results["llm_calls_incurred_by_empty_resume"] = n_calls_after - n_calls_before
    results["failure_record_gap"] = (
        "crash before first durable checkpoint leaves NO failure record; subsequent Command(resume=...) "
        f"silently re-executed {results['llm_calls_incurred_by_empty_resume']} LLM calls instead of failing fast"
    )

    write_out(f"{RUN_LABEL or 'default'}__8764", results)
    print(json.dumps(results, indent=1))
