"""LangGraph implementation: explicit state machine for the counting question.

The developer defines every node, every edge, and the loop condition.
The model only makes decisions INSIDE nodes (computing the answer from the ids).
Counting benchmark (Experiment A):
  COUNT_MODE=ids   : the ids land in state via a code call; the MODEL must
                     compute the count itself (its own arithmetic)
  COUNT_MODE=stats : a code node precomputes count/min/max; the model only
                     reads them back
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

from tools_counting import count_summary, fetch_ids, true_count  # noqa: E402

COUNT_MODE = os.environ.get("COUNT_MODE", "ids")

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
QUESTION = os.environ.get("QUESTION", "How many ids are there with id >= 9?")

llm = ChatOpenAI(
    model=MODEL,
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    default_headers={"X-Run-Label": RUN_LABEL},
)


class CountState(TypedDict):
    ids: list
    summary: dict
    answer: str


def load_ids(state: CountState) -> dict:
    # Deterministic data load (no LLM involved) - the developer wired this step
    return {"ids": fetch_ids()["ids"]}


def load_summary(state: CountState) -> dict:
    # Deterministic precompute (no LLM involved)
    return {"summary": count_summary()}


def compute_answer(state: CountState) -> dict:
    # The ONE LLM node: turn the state into the single answer line
    if COUNT_MODE == "stats":
        s = state["summary"]
        context = (
            f"Precomputed statistics for the id list:\n"
            f"count={s.get('count')}, min={s.get('min')}, max={s.get('max')}\n\n"
            f"Question: {QUESTION}\n"
            'Output the answer line "count=<number>" only. No commentary.'
        )
    else:
        joined = ", ".join(str(i) for i in state["ids"])
        context = (
            f"The id list:\n{joined}\n\n"
            f"Question: {QUESTION}\n"
            'Answer format: a single line "count=<number>". No commentary.'
        )
    resp = llm.invoke(context)
    return {"answer": resp.content}


workflow = StateGraph(CountState)
workflow.add_node("load_ids", load_ids)
workflow.add_node("load_summary", load_summary)
workflow.add_node("answer", compute_answer)

entry = "load_ids" if COUNT_MODE == "ids" else "load_summary"
workflow.set_entry_point(entry)
if entry == "load_ids":
    workflow.add_edge("load_ids", "answer")
else:
    workflow.add_edge("load_summary", "answer")
workflow.add_edge("answer", END)

graph = workflow.compile()

# the question's true predicate must match the tool layer's bounds (COUNT_LO/HI)
from tools_counting import HI, LO  # noqa: E402

t0 = time.time()
final = graph.invoke({"ids": [], "summary": {}, "answer": ""})
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"langgraph_result_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "langgraph",
            "run_label": RUN_LABEL,
            "count_mode": COUNT_MODE,
            "question": QUESTION,
            "answer": final["answer"],
            "true_count": true_count(final["ids"], LO, HI),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[langgraph] done in {elapsed:.1f}s ({RUN_LABEL})")
print(final["answer"][:400])
