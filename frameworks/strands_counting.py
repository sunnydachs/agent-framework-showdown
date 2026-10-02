"""Strands Agents implementation: ONE agent, model-driven counting loop.

The model decides everything: which tool to call, in what order, when done.
Counting benchmark (Experiment A):
  COUNT_MODE=ids   : the tool returns ONLY the id list; the model must report
                     the count of ids matching the threshold (its own arithmetic)
  COUNT_MODE=stats : the tool precomputes and returns count/min/max; the model
                     just answers those back
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from strands import Agent, tool  # noqa: E402
from strands.models.litellm import LiteLLMModel  # noqa: E402

from tools_counting import count_summary, fetch_ids  # noqa: E402

COUNT_MODE = os.environ.get("COUNT_MODE", "ids")

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
QUESTION = os.environ.get("QUESTION", "How many ids are there with id >= 9?")


@tool
def get_id_list() -> dict:
    """Return the full list of numeric ids.

    Returns:
        Dict with the id list under "ids".
    """
    return fetch_ids()


@tool
def get_count_summary() -> dict:
    """Return precomputed statistics (count, min, max) for the ids."""
    return count_summary()


SYSTEM_PROMPT = """You are a data analyst. You will be asked ONE question about a list of numeric ids.

Workflow you must follow:
1. Call get_id_list to obtain the ids.
2. Answer the question with the exact number asked for.

Answer format: a single line "count=<number>". No commentary, no explanation."""

model = LiteLLMModel(
    model_id="openai/" + MODEL,
    client_args={
        "base_url": BASE_URL,
        "api_key": "dummy",
        "extra_headers": {"X-Run-Label": RUN_LABEL},
    },
)

tools = [get_id_list] if COUNT_MODE == "ids" else [get_count_summary]

t0 = time.time()
agent = Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)
result = agent(QUESTION)
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"strands_result_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "strands",
            "run_label": RUN_LABEL,
            "count_mode": COUNT_MODE,
            "question": QUESTION,
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[strands] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:400])
