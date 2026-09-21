"""CrewAI: structured output via expected_output instruction (F experiment).

The role pipeline: the Writer agent is told the expected output is strict JSON.
Whether the final output actually parses and matches the schema is measured
post-run.

Run: RUN_LABEL=crewai__structured_run1 OPENAI_BASE_URL=http://127.0.0.1:8118/v1 \
     MODEL=<model> .venv-crewai/bin/python frameworks/crewai_structured.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from crewai import Agent, Crew, Task, LLM, Process  # noqa: E402

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

llm = LLM(
    model=f"openai/{MODEL}",
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    extra_headers={"X-Run-Label": RUN_LABEL},
)

writer = Agent(
    role="Tech Digest Writer",
    goal="Write a ~100-word digest and return it as strict JSON",
    backstory="You are a concise tech writer who always returns machine-parseable JSON.",
    llm=llm,
    allow_delegation=False,
)

write_task = Task(
    description=(
        "Write a digest of about 100 words summarizing these headlines into a "
        "flowing narrative, then output STRICT JSON with EXACTLY these keys:\n"
        f"{SCHEMA_SPEC}\n\n"
        "Headlines:\n"
        "AI agents headlines: open-source agent frameworks hit production milestone; "
        "model-driven agents quietly replace hand-coded orchestration; tool-calling "
        "reliability becomes the new benchmark; multi-agent swarms move to regulated "
        "enterprise workflows; observability standards emerge for tracing agent decisions.\n\n"
        "Output the JSON text only - no commentary, no markdown fences."
    ),
    expected_output=(
        'Strict JSON with exactly 4 keys: summary (string), word_count (integer), '
        'topics (array of strings), publish_ready (boolean). No markdown fences.'
    ),
    agent=writer,
)

crew = Crew(agents=[writer], tasks=[write_task], process=Process.sequential, verbose=False)

t0 = time.time()
result = crew.kickoff()
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"crewai_structured_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "crewai",
            "task": "structured",
            "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[crewai-structured] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:200])
