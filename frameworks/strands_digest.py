"""Strands Agents implementation: ONE agent, model-driven loop.

The model decides everything: which tool to call, in what order, when done.
We only hand it the two tools and a system prompt.
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

from tools import fetch_headlines, word_count  # noqa: E402

MODEL = os.environ.get("MODEL", "inclusionai/ling-3.0-flash-fin:free")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")


@tool
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


@tool
def check_word_count(text: str) -> dict:
    """Count words and characters in a text.

    Args:
        text: The text to count.
    """
    return word_count(text)


SYSTEM_PROMPT = """You are a tech news digest writer.

Workflow you must follow:
1. Call get_headlines for topic "AI agents" (count 5).
2. Write a digest of about 100 words summarizing the headlines into a flowing narrative.
3. Call check_word_count on your draft. If it is under 80 or over 120 words, revise the draft and check again.
4. Output the final digest text only."""

model = LiteLLMModel(
    model_id="openai/" + MODEL,
    client_args={"base_url": BASE_URL, "api_key": "dummy"},
)

t0 = time.time()
agent = Agent(model=model, tools=[get_headlines, check_word_count], system_prompt=SYSTEM_PROMPT)
result = agent("Write today's tech news digest.")
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "strands_result.json").write_text(
    json.dumps(
        {
            "framework": "strands",
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
            "n_tool_calls": len(agent.messages.tool_calls) if hasattr(agent.messages, "tool_calls") else None,
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[strands] done in {elapsed:.1f}s")
print(str(result)[:600])
