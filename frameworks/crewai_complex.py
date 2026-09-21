"""CrewAI implementation: role-based crew, complex task (topic comparison).

The "Researcher" and "Writer" roles split the work; the compare decision is
folded into the Researcher's task (role-based = the model decides inside the
role, the Crew orchestrates the handoff).
Task: complex - the B-scaling counterpart to the digest task.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines, word_count  # noqa: E402
from crewai import Agent, Crew, Task, LLM  # noqa: E402
from crewai.tools import tool  # noqa: E402

SCENARIO = os.environ.get("SCENARIO", "base")
WORD_MIN = int(os.environ.get("WORD_MIN", 80))
WORD_MAX = int(os.environ.get("WORD_MAX", 120))

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


@tool("Count words")
def check_word_count(text: str) -> dict:
    """Count words and characters in a text.

    Args:
        text: The text to count.
    """
    return word_count(text)


@tool("Fetch headlines")
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents" or "quantum computing".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


researcher = Agent(
    role="Senior Tech Researcher",
    goal=(
        "Collect recent headlines for BOTH topics ('AI agents' with count 5, "
        "'quantum computing' with count 4) using the fetch tool, then determine "
        "which topic has MORE headlines"
    ),
    backstory=(
        "You are a meticulous researcher who always uses tools to gather facts, "
        "never invents headlines, and counts carefully before comparing."
    ),
    llm=llm,
    tools=[get_headlines],
    allow_delegation=False,
)

writer = Agent(
    role="Tech Digest Writer",
    goal=(
        "Write a ~100-word digest of the WINNING topic's headlines "
        "(the one with more coverage) and verify its length with the word count tool"
    ),
    backstory="You are a concise tech writer who verifies word counts with tools before finishing.",
    llm=llm,
    tools=[check_word_count],
    allow_delegation=False,
)

research_task = Task(
    description=(
        "Call the fetch headlines tool TWICE: once for topic 'AI agents' with count 5, "
        "once for topic 'quantum computing' with count 4. "
        "Then compare: which topic returned MORE headlines? "
        "Return ONLY the winning topic name and its headlines, one per line, no commentary."
    ),
    expected_output="The winning topic name and its list of headlines, one per line.",
    agent=researcher,
)

write_task = Task(
    description=(
        "Write a digest of about 100 words summarizing the WINNING topic's headlines "
        "into a flowing narrative:\n{previous_output}"
        f"\nThen call the word count tool on your draft. If under {WORD_MIN} or over {WORD_MAX} words, revise and re-check. "
        "Return ONLY the final digest text."
    ),
    expected_output="The final digest text of about 100 words.",
    agent=writer,
    context=[research_task],
)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task], verbose=False)

t0 = time.time()
result = crew.kickoff()
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"crewai_complex_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "crewai",
            "task": "complex",
            "run_label": RUN_LABEL,
            "scenario": SCENARIO,
            "tool_variant": "base",
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[crewai-complex] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:400])
