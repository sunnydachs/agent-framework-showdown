"""Strands crash-resume (Experiment 4, Cell A comparison).

Strands has NO checkpointer / suspension primitive: an in-flight agent loop
lives in the process, and process death (SIGKILL) kills it. The approval gate
here is a BLOCKING tool: it prints SUSPENDED and waits for the human's
decision file - the "waiting for review" state. The driver SIGKILLs the
process mid-wait; the "resume" is a FULL re-run (there is no state to resume
into). Session survival is demonstrated with FileSessionManager (the file
persistence strands DOES have): the transcript survives process recreation,
but a transcript with a dangling tool_use (killed before the tool returned)
may not resume cleanly - both outcomes are recorded.

PHASE=run    : agent drafts, then ask_to_publish BLOCKS on the decision file
               (prints SUSPENDED). The driver SIGKILLs mid-wait.
PHASE=resume : the decision file is written by the driver first; the agent
               re-runs the WHOLE loop from scratch (full re-run cost) with
               the persisted session transcript; if that errors (dangling
               tool_use), one fallback run with a fresh session_id records
               the clean-re-run cost.

Run (driver): RUN_LABEL=strands__crash_run1 PHASE=run \
     OPENAI_BASE_URL=http://127.0.0.1:8118/v1 MODEL=<model> \
     .venv-strands/bin/python frameworks/strands_crash_idem.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines  # noqa: E402

from strands import Agent, tool  # noqa: E402
from strands.models.litellm import LiteLLMModel  # noqa: E402

PHASE = os.environ.get("PHASE", "run")
MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
DECISION_FILE = Path(os.environ.get("DECISION_FILE", "/tmp/strands_decision.json"))
SESSION_DIR = os.environ.get("STRANDS_SESSION_DIR", str(ROOT / "traces" / "strands_sessions"))
SESSION_ID = os.environ.get("STRANDS_SESSION_ID", RUN_LABEL or "crash-demo")
WAIT_TIMEOUT_S = float(os.environ.get("WAIT_TIMEOUT_S", "600"))
T0_PROC = time.time()


@tool
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


@tool
def ask_to_publish(article: str, summary: str = "") -> dict:
    """Ask the human reviewer to approve publishing this article. BLOCKS
    until the reviewer writes the decision.

    Args:
        article: The full draft text to publish.
        summary: A one-line summary for the reviewer.

    Returns:
        The reviewer's decision with an "approved" boolean.
    """
    # THE WAITING-FOR-REVIEW STATE - the process blocks HERE. The driver
    # SIGKILLs while the agent is suspended on this call.
    print(f"SUSPENDED phase1_s={time.time() - T0_PROC:.2f} waiting_for=decision_file", flush=True)
    deadline = time.time() + WAIT_TIMEOUT_S
    while time.time() < deadline:
        if DECISION_FILE.exists():
            break
        time.sleep(0.2)
    if not DECISION_FILE.exists():
        return {"approved": False, "reviewer": "timeout-no-decision"}
    d = json.loads(DECISION_FILE.read_text())
    return {"approved": bool(d.get("approved", False)), "reviewer": "scripted-reviewer"}


@tool
def publish_article(article: str) -> dict:
    """Publish the article. Only call this AFTER the reviewer approves.

    Args:
        article: The final draft text to publish.
    """
    return {"status": "published", "chars": len(article), "log": "strands-crash-publish"}


SYSTEM_PROMPT = """You are a tech news digest writer with a strict publishing rule.

Workflow you must follow:
1. Call get_headlines for topic "AI agents" (count 5).
2. Write a digest of about 60 words summarizing the headlines.
3. Call ask_to_publish with your draft to request human approval. It may block
   a while - that is the reviewer reading. Wait for it.
4. If the reviewer approves (approved=true), call publish_article with the SAME draft text.
5. If the reviewer rejects (approved=false), do NOT call publish_article. Output the final status text only.

The publish tool is destructive: NEVER call publish_article before the reviewer approves."""


def out_path(tag):
    d = ROOT / "outputs"
    d.mkdir(exist_ok=True)
    return d / f"strands_crash_{tag}.json"


def write_out(tag, payload):
    p = out_path(tag)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"[strands-crash] wrote {p.name}", flush=True)


def build_agent(session_id: str):
    model = LiteLLMModel(
        model_id="openai/" + MODEL,
        client_args={
            "base_url": BASE_URL,
            "api_key": "dummy",
            "extra_headers": {"X-Run-Label": RUN_LABEL},
        },
    )
    kwargs = {"model": model, "tools": [get_headlines, ask_to_publish, publish_article], "system_prompt": SYSTEM_PROMPT}
    try:
        from strands.session import FileSessionManager

        kwargs["session_manager"] = FileSessionManager(session_id=session_id, storage_dir=SESSION_DIR)
        print(f"[strands-crash] FileSessionManager attached: session={session_id}", flush=True)
    except Exception as e:
        print(f"[strands-crash] FileSessionManager unavailable: {e}", flush=True)
    return Agent(**kwargs)


def run_agent_once(session_id: str, resume_tag: str):
    t0 = time.time()
    error = None
    result = None
    try:
        result = build_agent(session_id)("Write today's tech news digest and publish it if approved.")
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:300]}"
    return round(time.time() - t0, 2), error, str(result)[:300] if result else None


if PHASE == "run":
    agent = build_agent(SESSION_ID)
    t0 = time.time()
    error = None
    try:
        result = agent("Write today's tech news digest and publish it if approved.")
        result_tail = str(result)[:300]
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:300]}"
        result_tail = None
    # Killed mid-wait: this output is normally never written (the process dies
    # inside ask_to_publish). Written only if the wait returned before the kill.
    if error is None and DECISION_FILE.exists() is False:
        write_out(f"{RUN_LABEL or 'default'}__phase1", {
            "framework": "strands", "phase": "run", "run_label": RUN_LABEL,
            "elapsed_s": round(time.time() - t0, 2), "result_tail": result_tail,
        })
        print("NOT KILLED - driver never sent SIGKILL", flush=True)
    elif error is not None:
        write_out(f"{RUN_LABEL or 'default'}__phase1", {
            "framework": "strands", "phase": "run", "run_label": RUN_LABEL,
            "elapsed_s": round(time.time() - t0, 2), "error": error,
        })
        print("AGENT ERROR before suspend", flush=True)

elif PHASE == "resume":
    # The decision file exists now (the driver wrote it). The "resume" is a
    # FULL re-run; first with the persisted session transcript, then (only if
    # that errors) a fresh-session fallback for the clean-re-run cost.
    resumed_s, resumed_err, resumed_tail = run_agent_once(SESSION_ID, "resume")
    payload = {
        "framework": "strands", "phase": "resume", "run_label": RUN_LABEL,
        "state_survived": False, "rerun": True,
        "resume_s": resumed_s, "resume_error": resumed_err, "resume_tail": resumed_tail,
    }
    if resumed_err is not None:
        # fallback: fresh session (clean re-run)
        fresh_s, fresh_err, fresh_tail = run_agent_once(SESSION_ID + "-fresh", "resume_fresh")
        payload["fallback_fresh_s"] = fresh_s
        payload["fallback_fresh_error"] = fresh_err
        payload["fallback_fresh_tail"] = fresh_tail
        payload["fallback_used"] = fresh_err is None
    write_out(f"{RUN_LABEL or 'default'}__resume", payload)
    print(f"[strands-crash] resume_s={resumed_s} error={resumed_err is not None} fallback={payload.get('fallback_used', False)}")
