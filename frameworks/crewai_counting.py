"""CrewAI implementation: role-based two-agent crew for the counting question.

The "Fetcher" and "Analyst" roles split the work; the Crew orchestrates.
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

from crewai import Agent, Crew, Task, LLM  # noqa: E402
from crewai.tools import tool  # noqa: E402

from tools_counting import count_summary, fetch_ids  # noqa: E402

COUNT_MODE = os.environ.get("COUNT_MODE", "ids")

MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
QUESTION = os.environ.get("QUESTION", "How many ids are there with id >= 9?")

llm = LLM(
    model=f"openai/{MODEL}",
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0,
    extra_headers={"X-Run-Label": RUN_LABEL},
)


@tool("Fetch ids")
def get_id_list() -> dict:
    """Return the full list of numeric ids.

    Returns:
        Dict with the id list under "ids".
    """
    return fetch_ids()


@tool("Count summary")
def get_count_summary() -> dict:
    """Return precomputed statistics (count, min, max) for the ids."""
    return count_summary()


fetcher = Agent(
    role="Data Fetcher",
    goal="Obtain the list of numeric ids using the get_id_list tool",
    backstory="You are a meticulous data fetcher who always uses tools to gather facts and never invents data.",
    llm=llm,
    tools=[get_id_list],
    allow_delegation=False,
)

analyst = Agent(
    role="Data Analyst",
    goal="Answer the counting question with the exact number",
    backstory="You are a precise analyst who answers with exact numbers.",
    llm=llm,
    tools=[get_count_summary] if COUNT_MODE == "stats" else [],
    allow_delegation=False,
)

fetch_task = Task(
    description=(
        "Call the get_id_list tool. "
        "Return ONLY the list of ids, comma-separated, no commentary."
    ),
    expected_output=(
        "A comma-separated list of ids."
        if COUNT_MODE == "ids"
        else "A statistics line with count, min, max."
    ),
    agent=fetcher,
)

analyze_task = Task(
    description=(
        "The ids (or their precomputed statistics) are available from the previous task.\n"
        + (
            "Count how many ids satisfy the question's condition and answer with that exact number."
            if COUNT_MODE == "ids"
            else "Answer with the exact count from the statistics."
        )
        + f"\nQuestion: {QUESTION}"
        + '\nAnswer format: a single line "count=<number>". No commentary.'
    ),
    expected_output='A single line "count=<number>".',
    agent=analyst,
    context=[fetch_task],
)

crew = Crew(agents=[fetcher, analyst], tasks=[fetch_task, analyze_task], verbose=False)

t0 = time.time()
result = crew.kickoff()
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"crewai_result_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "crewai",
            "run_label": RUN_LABEL,
            "count_mode": COUNT_MODE,
            "question": QUESTION,
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[crewai] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:400])
