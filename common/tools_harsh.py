"""Shared deterministic tools — HARSH schema-change variants (Experiment 5, H).

Four escalating schema changes to word_count, selected by env HARSH_LEVEL:
  rename : word_count(content: str)  — argument renamed; the task prompts
           still say text (same shape as tools_drift; the ladder's baseline)
  type   : word_count(content: int) — the argument TYPE changed: content is
           now a numeric document id. Passing the draft text raises TypeError
           (the tool layer turns that into an error result for the model);
           a schema-valid int still fails ("document not found"), so real
           verification is impossible at this level by design.
  remove : word_count()             — the text argument is DELETED entirely.
           The tool ignores the caller and returns a static placeholder
           count, so the digest can never actually be verified.
  add    : word_count(content: str, note: str) — a NEW REQUIRED argument the
           prompt never mentions; the model must invent a value for `note`
           or fail. If it does, the count is real again.

HEADLINES + fetch_headlines are unchanged from tools_drift. The task prompts
(common/TASK.md) stay FIXED across all levels — the whole point is
prompt/schema divergence.
"""
import os

HARSH_LEVEL = os.environ.get("HARSH_LEVEL", "rename")

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


# static text the remove-level tool counts instead of the caller's draft
_STATIC_TEXT = "The word_count tool no longer accepts text input."


def _wc_rename(content: str) -> dict:
    """Count words and characters in a text.

    Args:
        content: The text to count.
    """
    if not isinstance(content, str):
        raise TypeError(f"content must be a string, got {type(content).__name__}")
    words = len([w for w in content.split() if w.strip()])
    return {"word_count": words, "char_count": len(content)}


def _wc_type(content: int) -> dict:
    """Count words in a stored document (by id).

    Args:
        content: Numeric id of the document to count.
    """
    if isinstance(content, bool) or not isinstance(content, int):
        raise TypeError(f"content must be an integer document id, got {type(content).__name__}")
    # no document store exists -> a schema-valid call still cannot verify a draft
    return {"error": f"document {content} not found"}


def _wc_remove() -> dict:
    """Return the current word count (text input no longer supported)."""
    return {"word_count": len(_STATIC_TEXT.split()), "char_count": len(_STATIC_TEXT)}


def _wc_add(content: str, note: str) -> dict:
    """Count words and characters in a text.

    Args:
        content: The text to count.
        note: Short note explaining why this count is requested.
    """
    if not isinstance(content, str):
        raise TypeError(f"content must be a string, got {type(content).__name__}")
    if not isinstance(note, str) or not note.strip():
        raise TypeError("note must be a non-empty string")
    words = len([w for w in content.split() if w.strip()])
    return {"word_count": words, "char_count": len(content), "note": note}


_VARIANTS = {
    "rename": _wc_rename,
    "type": _wc_type,
    "remove": _wc_remove,
    "add": _wc_add,
}
if HARSH_LEVEL not in _VARIANTS:
    raise ValueError(f"HARSH_LEVEL must be one of {sorted(_VARIANTS)}, got {HARSH_LEVEL!r}")

word_count = _VARIANTS[HARSH_LEVEL]

TOOLS_REGISTRY = {"fetch_headlines": fetch_headlines, "word_count": word_count}
