"""LangGraph implementation: explicit state machine with a verification loop.

The developer defines every node, every edge, and the loop condition.
The model only makes decisions INSIDE nodes (writing the draft).
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402

from tools import fetch_headlines, word_count  # noqa: E402

MODEL = os.environ.get("MODEL", "inclusionai/ling-3.0-flash-fin:free")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")

llm = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY, temperature=0)


class DigestState(TypedDict):
    topic: str
    headlines: list
    draft: str
    wc: int
    revisions: int


def collect_headlines(state: DigestState) -> dict:
    # Deterministic tool call (no LLM involved) - the developer wired this step
    data = fetch_headlines(state["topic"], 5)
    return {"headlines": data["headlines"]}


def write_draft(state: DigestState) -> dict:
    joined = "\n".join(f"- {h}" for h in state["headlines"])
    prompt = (
        "Write a tech news digest of about 100 words based on these headlines.\n"
        f"Output the digest text only.\n\nHeadlines:\n{joined}"
    )
    resp = llm.invoke(prompt)
    return {"draft": resp.content, "revisions": state.get("revisions", 0)}


def verify_word_count(state: DigestState) -> dict:
    # Deterministic check (no LLM involved)
    return {"wc": word_count(state["draft"])["word_count"]}


def should_revise(state: DigestState) -> str:
    wc = state["wc"]
    if wc < 80:
        return "too_short"
    if wc > 120:
        return "too_long"
    return "ok"


def revise_draft(state: DigestState) -> dict:
    direction = "expand" if state["wc"] < 80 else "shorten"
    prompt = (
        f"The following digest is {state['wc']} words. Please {direction} it to about 100 words.\n"
        f"Output the revised digest text only.\n\n{state['draft']}"
    )
    resp = llm.invoke(prompt)
    return {"draft": resp.content, "revisions": state.get("revisions", 0) + 1}


workflow = StateGraph(DigestState)
workflow.add_node("collect", collect_headlines)
workflow.add_node("write", write_draft)
workflow.add_node("verify", verify_word_count)
workflow.add_node("revise", revise_draft)

workflow.set_entry_point("collect")
workflow.add_edge("collect", "write")
workflow.add_edge("write", "verify")
workflow.add_conditional_edges(
    "verify",
    should_revise,
    {"too_short": "revise", "too_long": "revise", "ok": END},
)
workflow.add_edge("revise", "verify")

graph = workflow.compile()

t0 = time.time()
final = graph.invoke({"topic": "AI agents", "headlines": [], "draft": "", "wc": 0, "revisions": 0})
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "langgraph_result.json").write_text(
    json.dumps(
        {
            "framework": "langgraph",
            "elapsed_s": round(elapsed, 2),
            "result": final["draft"],
            "word_count": final["wc"],
            "revisions": final["revisions"],
            "n_llm_calls": len(trace_llm_calls) if False else None,
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[langgraph] done in {elapsed:.1f}s, wc={final['wc']}, revisions={final['revisions']}")
print(final["draft"][:600])
