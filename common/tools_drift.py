"""Shared deterministic tools — DRIFT variant.

Same functions as tools.py, but the word-count tool now takes `content`
while the task prompts (written earlier) still say `text`. This simulates a
tool schema change without updating all call sites / prompts.
"""

HEADLINES = {
    "AI agents": [
        "Open-source agent frameworks hit production milestone as adoption triples",
        "Model-driven agents quietly replace hand-coded orchestration in startups",
        "Tool-calling reliability becomes the new benchmark for frontier models",
        "Multi-agent swarms move from demos to regulated enterprise workflows",
        "Observability standards emerge for tracing agent decisions end to end",
        "MCP ecosystem crosses ten thousand servers as tools become commodities",
        "Agent memory startups consolidate as context windows keep growing",
        "Cost per solved task overtakes model quality as the buying metric",
    ],
    "quantum computing": [
        "Error-corrected logical qubits cross the thousand-qubit threshold",
        "Post-quantum cryptography migration deadlines tighten for banks",
        "Quantum simulation cuts drug discovery timelines by half",
        "Hybrid classical-quantum workflows enter standard cloud catalogs",
    ],
}


def fetch_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents" or "quantum computing".
        count: How many headlines to return (1-8).

    Returns:
        Dict with the topic and a list of headline strings.
    """
    pool = HEADLINES.get(topic, HEADLINES["AI agents"])
    n = max(1, min(int(count), len(pool)))
    return {"topic": topic, "headlines": pool[:n]}


def word_count(content: str) -> dict:
    """Count words and characters in a text.

    Args:
        content: The text to count.
    """
    words = len([w for w in content.split() if w.strip()])
    return {"word_count": words, "char_count": len(content)}


TOOLS_REGISTRY = {"fetch_headlines": fetch_headlines, "word_count": word_count}
