"""LangGraph: structured output via prompt instruction (F experiment).

The single LLM call is instructed to output strict JSON. Whether the output
actually parses and matches the schema is measured post-run. No tool-based
self-check - the graph has no validation node here (that IS the comparison:
LangGraph's own verify/revise loop could be extended with a schema check, but
the plain output-instruction path is what most teams ship first).

Run: RUN_LABEL=langgraph__structured_run1 OPENAI_BASE_URL=http://127.0.0.1:8118/v1 \
     MODEL=<model> .venv-langgraph/bin/python frameworks/langgraph_structured.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")

SCHEMA_SPEC = """{
  "summary": "string - the ~100-word digest",
  "word_count": "integer - word count of summary",
  "topics": "array of strings - topics covered",
  "publish_ready": "boolean - true if the summary is 80-120 words"
}"""

llm = ChatOpenAI(
    model=MODEL,
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    default_headers={"X-Run-Label": RUN_LABEL},
)

data = fetch_headlines("AI agents", 5)
joined = "\n".join(f"- {h}" for h in data["headlines"])
prompt = (
    "Write a tech news digest of about 100 words based on these headlines.\n"
    "Then output STRICT JSON with EXACTLY these keys:\n"
    f"{SCHEMA_SPEC}\n\n"
    "Output the JSON text only - no commentary, no markdown fences.\n\n"
    f"Headlines:\n{joined}"
)

t0 = time.time()
resp = llm.invoke(prompt)
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"langgraph_structured_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "langgraph",
            "task": "structured",
            "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2),
            "result": resp.content,
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[langgraph-structured] done in {elapsed:.1f}s ({RUN_LABEL})")
print(resp.content[:200])
