"""CrewAI: Task(human_input=True) HITL (D experiment).

The OSS pattern: the crew pauses for console feedback after the task completes.
CrewAI's HumanInputConsoleInterface prompts on stdin - in the benchmark the
"human" is scripted: APPROVAL_MODE env is piped via stdin (approve/reject).

What the pause actually looks like (which LLM calls happen before the pause,
whether the feedback re-enters the conversation, whether rejection stops the
publish) is what the traces show.

Run: RUN_LABEL=crewai__hitl_approve_run1 APPROVAL_MODE=approve \
     OPENAI_BASE_URL=http://127.0.0.1:8118/v1 MODEL=<model> \
     .venv-crewai/bin/python frameworks/crewai_hitl.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines  # noqa: E402
from crewai import Agent, Crew, Task, LLM, Process  # noqa: E402

APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "approve")
MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")

llm = LLM(
    model=f"openai/{MODEL}",
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    extra_headers={"X-Run-Label": RUN_LABEL},
)

writer = Agent(
    role="Tech Digest Writer",
    goal="Write a ~100-word digest of the given headlines",
    backstory="You are a concise tech writer who writes flowing narratives.",
    llm=llm,
    allow_delegation=False,
)

write_task = Task(
    description=(
        "Write a digest of about 100 words summarizing these headlines "
        "(fetch them yourself is NOT needed - they are provided below) into a "
        "flowing narrative:\nAI agents headlines: open-source agent frameworks "
        "hit production milestone; model-driven agents quietly replace "
        "hand-coded orchestration; tool-calling reliability becomes the new "
        "benchmark; multi-agent swarms move to regulated enterprise workflows; "
        "observability standards emerge for tracing agent decisions."
    ),
    expected_output="The final digest text of about 100 words.",
    agent=writer,
    human_input=True,  # THE HITL GATE - the crew pauses for feedback here
)

crew = Crew(agents=[writer], tasks=[write_task], process=Process.sequential, verbose=False)

# Script the "human": CrewAI's HumanInputConsoleInterface calls builtins
# input() after EVERY task iteration, so patch builtins.input to feed a
# scripted sequence. IMPORTANT: CrewAI re-runs the task on every non-empty
# feedback and prompts again - so reject = ONE feedback line, then "" (accept)
# on the next prompt. Feeding the same rejection forever = infinite loop
# (measured: 131 LLM calls, prompt growing 240 -> 6,561 before the kill).
# approve -> "" (accept the output as-is)
# reject  -> feedback text once, then ""
import builtins
from itertools import chain, repeat

t0 = time.time()
if APPROVAL_MODE == "approve":
    answers = chain([""], repeat(""))
else:
    answers = chain(
        ["REJECTED: do not publish this. Shorten it and add a caution line."],
        repeat(""),
    )
_real_input = builtins.input
builtins.input = lambda *a, **k: next(answers)
try:
    result = crew.kickoff()
finally:
    builtins.input = _real_input
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"crewai_hitl_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "crewai",
            "task": "hitl",
            "approval_mode": APPROVAL_MODE,
            "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[crewai-hitl] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:200])
