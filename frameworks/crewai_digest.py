"""CrewAI implementation: role-based two-agent crew with task handoff.

The "Researcher" and "Writer" roles split the work; the Crew orchestrates.
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

from crewai import Agent, Crew, Task, LLM  # noqa: E402
from crewai.tools import tool  # noqa: E402

TOOL_VARIANT = os.environ.get("TOOL_VARIANT", "base")
if TOOL_VARIANT == "drift":
    from tools_drift import fetch_headlines, word_count  # noqa: E402
elif TOOL_VARIANT == "harsh":
    from tools_harsh import fetch_headlines, word_count  # noqa: E402
else:
    from tools import fetch_headlines, word_count  # noqa: E402

# HARSH_LEVEL shapes what schema the model actually sees (unlike drift, the
# harsh wrapper does NOT paper over the change):
#   rename: check_word_count(content)          (renamed arg)
#   type:   check_word_count(content: int)      (type change)
#   remove: check_word_count()                  (arg deleted)
#   add:    check_word_count(content, note)     (new required arg)
HARSH_LEVEL = os.environ.get("HARSH_LEVEL", "rename")

SCENARIO = os.environ.get("SCENARIO", "base")
WORD_MIN = int(os.environ.get("WORD_MIN", 95 if SCENARIO == "tight" else 80))
WORD_MAX = int(os.environ.get("WORD_MAX", 105 if SCENARIO == "tight" else 120))

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

# drift variant: keep the OLD wrapper signature `text` (prompts say `text`),
# but the underlying function now expects `content` -> keyword mismatch at runtime
if TOOL_VARIANT == "drift":

    @tool("Count words")
    def check_word_count(text: str) -> dict:
        """Count words and characters in a text.

        Args:
            text: The text to count.
        """
        return word_count(**{"content": text})

elif TOOL_VARIANT == "harsh" and HARSH_LEVEL == "type":

    @tool("Count words")
    def check_word_count(content: int) -> dict:
        """Count words and characters in a text.

        Args:
            content: The text to count.
        """
        return word_count(content)

elif TOOL_VARIANT == "harsh" and HARSH_LEVEL == "remove":

    @tool("Count words")
    def check_word_count() -> dict:
        """Count words and characters in a text."""
        return word_count()

elif TOOL_VARIANT == "harsh" and HARSH_LEVEL == "add":

    @tool("Count words")
    def check_word_count(content: str, note: str) -> dict:
        """Count words and characters in a text.

        Args:
            content: The text to count.
            note: Short note explaining why this count is requested.
        """
        return word_count(content=content, note=note)

elif TOOL_VARIANT == "harsh":

    @tool("Count words")
    def check_word_count(content: str) -> dict:
        """Count words and characters in a text.

        Args:
            content: The text to count.
        """
        return word_count(content)

else:

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
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


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
(out_dir / f"crewai_result_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "crewai",
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
print(f"[crewai] done in {elapsed:.1f}s ({RUN_LABEL})")
print(str(result)[:400])
