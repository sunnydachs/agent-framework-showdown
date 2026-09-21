"""Strands: structured output via tool-based self-check (F experiment).

The model writes the digest, calls validate_output (a deterministic schema
checker), fixes any violations, and outputs the final JSON. Whether the final
output actually parses as JSON and matches the schema is measured post-run.

Run: RUN_LABEL=strands__structured_run1 OPENAI_BASE_URL=http://127.0.0.1:8118/v1 \
     MODEL=<model> .venv-strands/bin/python frameworks/strands_structured.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines, word_count  # noqa: E402

from strands import Agent, tool  # noqa: E402
from strands.models.litellm import LiteLLMModel  # noqa: E402

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
RUN_LABEL = os.environ.get("RUN_LABEL", "")

SCHEMA_SPEC = """{
  "summary": "string - the ~100-word digest",
  "word_count": "integer - word count of summary",
  "topics": "array of strings - topics covered (e.g. [\"AI agents\"])",
  "publish_ready": "boolean - true if the summary is 80-120 words"
}"""


@tool
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


@tool
def validate_output(output_json: str) -> dict:
    """Validate the output JSON against the required schema.

    Args:
        output_json: The JSON string to validate.

    Returns:
        Dict with valid (bool) and violations (list of strings).
    """
    violations = []
    try:
        d = json.loads(output_json)
    except Exception as e:
        return {"valid": False, "violations": [f"not valid JSON: {e}"]}
    if not isinstance(d, dict):
        return {"valid": False, "violations": ["not a JSON object"]}
    for key, typ in [("summary", str), ("word_count", int), ("topics", list), ("publish_ready", bool)]:
        if key not in d:
            violations.append(f"missing key: {key}")
        elif not isinstance(d[key], typ):
            violations.append(f"wrong type for {key}: expected {typ.__name__}, got {type(d[key]).__name__}")
    if isinstance(d.get("word_count"), int) and isinstance(d.get("summary"), str):
        actual = len([w for w in d["summary"].split() if w.strip()])
        if d["word_count"] != actual:
            violations.append(f"word_count mismatch: claimed {d['word_count']}, actual {actual}")
        if not (80 <= actual <= 120):
            violations.append(f"summary is {actual} words, outside 80-120 band")
    return {"valid": not violations, "violations": violations}


SYSTEM_PROMPT = f"""You are a tech news digest writer. Your output MUST be strict JSON.

Workflow you must follow:
1. Call get_headlines for topic "AI agents" (count 5).
2. Write a digest of about 100 words summarizing the headlines.
3. Build the output JSON with EXACTLY these keys: {SCHEMA_SPEC}
4. Call validate_output with your JSON string. If it reports violations, fix them and validate again.
5. Output the final JSON text only - no commentary, no markdown fences.

The final output must parse as JSON with all 4 keys and correct types."""


model = LiteLLMModel(
    model_id="openai/" + MODEL,
    client_args={
        "base_url": BASE_URL,
        "api_key": "dummy",
        "extra_headers": {"X-Run-Label": RUN_LABEL},
    },
)

t0 = time.time()
agent = Agent(model=model, tools=[get_headlines, validate_output], system_prompt=SYSTEM_PROMPT)
result = agent("Write today's tech news digest as strict JSON.")
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"strands_structured_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "strands",
            "task": "structured",
            "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[strands-structured] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:200])
