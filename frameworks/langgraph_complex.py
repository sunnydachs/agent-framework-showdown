"""LangGraph implementation: explicit state machine with branching + verification.

The developer wires EVERY node: two collect nodes, an explicit compare/branch
decision in code, and the verify/revise loop. The model only writes drafts.
Task: complex (topic comparison) - the B-scaling counterpart to the digest task.
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines, word_count  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402

SCENARIO = os.environ.get("SCENARIO", "base")
WORD_MIN = int(os.environ.get("WORD_MIN", 80))
WORD_MAX = int(os.environ.get("WORD_MAX", 120))
MAX_REVISIONS = int(os.environ.get("MAX_REVISIONS", 4))

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


class ComplexState(TypedDict):
    agent_hl: list
    quantum_hl: list
    winner: str
    draft: str
    wc: int
    revisions: int


def collect_agent(state: ComplexState) -> dict:
    data = fetch_headlines("AI agents", 5)  # deterministic tool call in code
    return {"agent_hl": data["headlines"]}


def collect_quantum(state: ComplexState) -> dict:
    data = fetch_headlines("quantum computing", 4)  # deterministic tool call in code
    return {"quantum_hl": data["headlines"]}


def compare_and_pick(state: ComplexState) -> dict:
    # THE BRANCH DECISION - in code, not in a prompt. This is what LangGraph buys.
    winner = "AI agents" if len(state["agent_hl"]) >= len(state["quantum_hl"]) else "quantum computing"
    return {"winner": winner}


def write_draft(state: ComplexState) -> dict:
    hl = state["agent_hl"] if state["winner"] == "AI agents" else state["quantum_hl"]
    joined = "\n".join(f"- {h}" for h in hl)
    prompt = (
        f"Write a tech news digest of about 100 words based on these {state['winner']} headlines.\n"
        f"Output the digest text only.\n\nHeadlines:\n{joined}"
    )
    resp = llm.invoke(prompt)
    return {"draft": resp.content, "revisions": state.get("revisions", 0)}


def verify_word_count(state: ComplexState) -> dict:
    return {"wc": word_count(state["draft"])["word_count"]}


def should_revise(state: ComplexState) -> str:
    if state["revisions"] >= MAX_REVISIONS:
        return "give_up"
    wc = state["wc"]
    if wc < WORD_MIN:
        return "too_short"
    if wc > WORD_MAX:
        return "too_long"
    return "ok"


def revise_draft(state: ComplexState) -> dict:
    direction = "expand" if state["wc"] < WORD_MIN else "shorten"
    prompt = (
        f"The following digest is {state['wc']} words. Please {direction} it to about 100 words.\n"
        f"Output the revised digest text only.\n\n{state['draft']}"
    )
    resp = llm.invoke(prompt)
    return {"draft": resp.content, "revisions": state.get("revisions", 0) + 1}


workflow = StateGraph(ComplexState)
workflow.add_node("collect_agent", collect_agent)
workflow.add_node("collect_quantum", collect_quantum)
workflow.add_node("compare", compare_and_pick)
workflow.add_node("write", write_draft)
workflow.add_node("verify", verify_word_count)
workflow.add_node("revise", revise_draft)

workflow.set_entry_point("collect_agent")
workflow.add_edge("collect_agent", "collect_quantum")
workflow.add_edge("collect_quantum", "compare")
workflow.add_edge("compare", "write")
workflow.add_edge("write", "verify")
workflow.add_conditional_edges(
    "verify",
    should_revise,
    {"too_short": "revise", "too_long": "revise", "ok": END, "give_up": END},
)
workflow.add_edge("revise", "verify")

graph = workflow.compile()

t0 = time.time()
final = graph.invoke({"agent_hl": [], "quantum_hl": [], "winner": "", "draft": "", "wc": 0, "revisions": 0})
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"langgraph_complex_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "langgraph",
            "task": "complex",
            "run_label": RUN_LABEL,
            "scenario": SCENARIO,
            "tool_variant": "base",
            "elapsed_s": round(elapsed, 2),
            "result": final["draft"],
            "winner": final["winner"],
            "word_count": final["wc"],
            "revisions": final["revisions"],
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[langgraph-complex] done in {elapsed:.1f}s, winner={final['winner']}, wc={final['wc']}, revisions={final['revisions']} ({RUN_LABEL})")
print(final["draft"][:400])
