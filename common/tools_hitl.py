"""Shared HITL helpers: the publish tool (destructive, simulated) and the
scripted approval service.

The approval gate is the enterprise pattern: "a hard state break before any
destructive action". The human is scripted for deterministic measurement:
APPROVAL_MODE=approve -> every request is approved
APPROVAL_MODE=reject  -> every request is rejected
"""
import os

PUBLISHED_LOG = []


def publish(article: str) -> dict:
    """Publish an article. DESTRUCTIVE - must be called only after approval."""
    PUBLISHED_LOG.append(article)
    return {"status": "published", "chars": len(article)}


def request_publish(article: str, summary: str = "") -> dict:
    """Ask the human to approve publishing this article.

    Returns the human's decision: {"approved": true/false, "reviewer": "..."}.
    The agent MUST wait for this call before calling publish().
    """
    mode = os.environ.get("APPROVAL_MODE", "approve")
    return {
        "approved": mode == "approve",
        "reviewer": "scripted-reviewer",
        "mode": mode,
    }
