"""CrewAI implementation: role-based two-agent crew with task handoff.

The "Researcher" and "Writer" roles split the work; the Crew orchestrates.
Each agent gets the two shared tools (used inside their task prompts).
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

from tools import fetch_headlines, word_count  # noqa: E402

MODEL = os.environ.get("MODEL", "inclusionai/ling-3.0-flash-fin:free")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")

llm = LLM(model=f"openai/{MODEL}", base_url=BASE_URL, api_key=API_KEY, temperature=0)

# annotate to avoid lint noise on sys.path injection
_ = llm


@tool("Fetch headlines")
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


@tool("Count words")
def check_word_count(text: str) -> dict:
    """Count words and characters in a text.

    Args:
        text: The text to count.
    """
    return word_count(text)


researcher = Agent(
    role="Senior Tech Researcher",
    goal="Collect exactly 5 recent headlines about the topic 'AI agents' using the fetch tool",
    backstory="You are a meticulous researcher who always uses tools to gather facts and never invents headlines.",
    llm=llm,
    tools=[get_headlines],
    allow_delegation=False,
)

writer = Agent(
    role="Tech Digest Writer",
    goal="Write a ~100-word digest of the given headlines and verify its length with the word count tool",
    backstory="You are a concise tech writer who verifies word counts with tools before finishing.",
    llm=llm,
    tools=[check_word_count],
    allow_delegation=False,
)

research_task = Task(
    description=(
        "Call the fetch headlines tool for topic 'AI agents' with count 5. "
        "Return ONLY the list of headlines, one per line, no commentary."
    ),
    expected_output="A list of 5 headlines, one per line.",
    agent=researcher,
)

write_task = Task(
    description=(
        "Write a digest of about 100 words summarizing these headlines into a flowing narrative:\n"
        "{previous_output}"
        "\nThen call the word count tool on your draft. If under 80 or over 120 words, revise and re-check. "
        "Return ONLY the final digest text."
    ),
    expected_output="The final digest text of about 100 words.",
    agent=writer,
    context=[research_task],
)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task], verbose=True)

t0 = time.time()
result = crew.kickoff()
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "crewai_result.json").write_text(
    json.dumps(
        {
            "framework": "crewai",
            "elapsed_s": round(elapsed, 2),
            "result": str(result),
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[crewai] done in {elapsed:.1f}s")
print(str(result)[:600])
