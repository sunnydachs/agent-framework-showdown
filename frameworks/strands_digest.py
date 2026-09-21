"""Strands Agents implementation: ONE agent, model-driven loop.

The model decides everything: which tool to call, in what order, when done.
Scenarios:
  SCENARIO=base  : 80-120 word band
  SCENARIO=tight : 95-105 word band (forces verify/revise loop)
  TOOL_VARIANT=drift: word_count tool now takes `content`, prompts still say `text`
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

TOOL_VARIANT = os.environ.get("TOOL_VARIANT", "base")
if TOOL_VARIANT == "drift":
    from tools_drift import fetch_headlines, word_count  # noqa: E402
else:
    from tools import fetch_headlines, word_count  # noqa: E402

SCENARIO = os.environ.get("SCENARIO", "base")
WORD_MIN = int(os.environ.get("WORD_MIN", 95 if SCENARIO == "tight" else 80))
WORD_MAX = int(os.environ.get("WORD_MAX", 105 if SCENARIO == "tight" else 120))

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
RUN_LABEL = os.environ.get("RUN_LABEL", "")

if TOOL_VARIANT == "drift":

    @tool
    def check_word_count(content: str) -> dict:
        """Count words and characters in a text."""
        return word_count(content)

else:

    @tool
    def check_word_count(text: str) -> dict:
        """Count words and characters in a text.

        Args:
            text: The text to count.
        """
        return word_count(text)


@tool
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


SYSTEM_PROMPT = f"""You are a tech news digest writer.

Workflow you must follow:
1. Call get_headlines for topic "AI agents" (count 5).
2. Write a digest of about 100 words summarizing the headlines into a flowing narrative.
3. Call check_word_count on your draft. If it is under {WORD_MIN} or over {WORD_MAX} words, revise the draft and check again.
4. Output the final digest text only."""

model = LiteLLMModel(
    model_id="openai/" + MODEL,
    client_args={
        "base_url": BASE_URL,
        "api_key": "dummy",
        "extra_headers": {"X-Run-Label": RUN_LABEL},
    },
)

t0 = time.time()
agent = Agent(model=model, tools=[get_headlines, check_word_count], system_prompt=SYSTEM_PROMPT)
result = agent("Write today's tech news digest.")
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"strands_result_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "strands",
            "run_label": RUN_LABEL,
            "scenario": SCENARIO,
            "tool_variant": TOOL_VARIANT,
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[strands] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:400])
