"""Complex task: "Topic comparison" agent - the B-scaling counterpart to the digest task.

Task shape: branching + 2+ tool calls (vs the linear digest task):
  1. Fetch headlines for topic "AI agents" (5)
  2. Fetch headlines for topic "quantum computing" (4)
  3. Compare coverage: which topic has MORE headlines (the deterministic data
     has 8 vs 4, so "AI agents" wins on count) -> the model must decide/branch
  4. Write a 80-120 word digest of the WINNING topic's headlines
  5. Verify word count, revise if out of band

Scenarios: SCENARIO=base (80-120 band). Same 3 frameworks, same proxy, same model.
Run labels: <framework>__complex_run<N> via X-Run-Label.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

TOOL_VARIANT = os.environ.get("TOOL_VARIANT", "base")
if TOOL_VARIANT == "drift":
    from tools_drift import fetch_headlines, word_count  # noqa: E402
else:
    from tools import fetch_headlines, word_count  # noqa: E402

SCENARIO = os.environ.get("SCENARIO", "base")
WORD_MIN = int(os.environ.get("WORD_MIN", 80))
WORD_MAX = int(os.environ.get("WORD_MAX", 120))

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")

# ============================================================
# Strands: ONE agent, model-driven loop (same as digest task but branching)
# ============================================================
from strands import Agent, tool  # noqa: E402
from strands.models.litellm import LiteLLMModel  # noqa: E402

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
        topic: News topic to search for, e.g. "AI agents" or "quantum computing".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


SYSTEM_PROMPT = f"""You are a tech news digest writer.

Workflow you must follow:
1. Call get_headlines for topic "AI agents" (count 5).
2. Call get_headlines for topic "quantum computing" (count 4).
3. Compare the two headline sets: determine which topic has MORE headlines.
4. Write a digest of about 100 words summarizing the WINNING topic's headlines into a flowing narrative.
5. Call check_word_count on your draft. If it is under {WORD_MIN} or over {WORD_MAX} words, revise the draft and check again.
6. Output the final digest text only."""

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
result = agent("Write today's tech news digest for the winning topic.")
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"strands_complex_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "strands",
            "task": "complex",
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
print(f"[strands-complex] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:400])
