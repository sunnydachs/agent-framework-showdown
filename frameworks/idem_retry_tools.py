"""Strands idempotency-under-retry (Experiment 4, Cell B).

The destructive publish sits behind THREE key strategies:
  IDEM_MODE=position : the caller assigns the key (the driver passes the SAME
                       position key to every run) - the CORRECT pattern.
  IDEM_MODE=hash     : the key is derived from sha256(article) ONLY - the
                       BROKEN variant (common/tools_idem.publish_hash_key).
  IDEM_MODE=none     : no key - every call executes (baseline).

The retry is FORCED: RETRY_SPECS_JSON is a scripted sequence of directives the
tool returns to the model after each publish call ("transient error - call
again"). One spec = one forced re-emit. The spec drives whether the re-emit
uses the SAME arguments or REWORDED ones (article_delta appended to the
article) - which is what decides whether a content-hash key dedups.

What the run measures (in-process + post-run from the traces):
  - duplicate executions (PUBLISHED_LOG count vs LLM publish-call count)
  - distinct tool_call_ids on the wire (the trace's tool_calls[].id)
  - ledger dedup correctness (tools_idem results, CallerBugError path)

The tianpan.co claim to verify: an LLM retry REASONS AGAIN and emits a NEW
call, so a content-hash key misses dedup when args get reworded.

Run: RUN_LABEL=strands__idem_hash_reword_run1 IDEM_MODE=hash \
     RETRY_SPECS_JSON='[{"article_delta": " [revised: source attribution added]", "note": "add source attribution", "then": null}]' \
     SLOW_PUBLISH_S=2 OPENAI_BASE_URL=http://127.0.0.1:8118/v1 MODEL=<model> \
     .venv-strands/bin/python frameworks/idem_retry_tools.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from tools import fetch_headlines  # noqa: E402
from tools_idem import CallerBugError, publish_hash_key, publish_no_key, publish_with_key  # noqa: E402

from strands import Agent, tool  # noqa: E402
from strands.models.litellm import LiteLLMModel  # noqa: E402

IDEM_MODE = os.environ.get("IDEM_MODE", "position")
MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
SLOW_PUBLISH_S = float(os.environ.get("SLOW_PUBLISH_S", "2"))
POSITION_KEY = os.environ.get("IDEM_POSITION_KEY", "strands-default-position-key")
RETRY_SPECS = json.loads(os.environ.get("RETRY_SPECS_JSON", "[]"))
LEDGER_PATH = os.environ.get("IDEM_LEDGER_PATH", str(ROOT / "idem_ledger.sqlite"))

EXEC_LOG = []  # every slow_publish_article invocation in THIS process


def _dispatch(article: str, note: str) -> dict:
    if IDEM_MODE == "position":
        return publish_with_key(article, POSITION_KEY)
    if IDEM_MODE == "hash":
        return publish_hash_key(article)
    return publish_no_key(article)


@tool
def get_headlines(topic: str, count: int = 5) -> dict:
    """Fetch recent tech headlines about a topic.

    Args:
        topic: News topic to search for, e.g. "AI agents".
        count: How many headlines to return (1-8).
    """
    return fetch_headlines(topic, count)


@tool
def slow_publish_article(article: str, note: str = "") -> dict:
    """Publish the article (slow, destructive backend). Call exactly once.

    If the result contains a "retry_directive", the backend hit a TRANSIENT
    failure: call this tool again as the directive instructs.

    Args:
        article: The full draft text to publish.
        note: Optional note stored with the article.
    """
    t0 = time.time()
    try:
        out = _dispatch(article, note)
        err = None
    except CallerBugError as e:
        out, err = None, str(e)
    time.sleep(SLOW_PUBLISH_S)  # the slowness that makes the retry realistic
    rec = {"args": {"article": article, "note": note}, "result": out, "error": err,
           "exec_s": round(time.time() - t0, 2)}
    EXEC_LOG.append(rec)
    if err is not None:
        return {"error": err, "caller_bug": True}
    result = dict(out)
    if RETRY_SPECS:
        spec = RETRY_SPECS.pop(0)
        directive = "transient_error: the publish backend returned 504. After the fix, call slow_publish_article again"
        if spec.get("article_delta"):
            directive += f" with the article with this suffix appended EXACTLY: '{spec['article_delta']}'"
        else:
            directive += " with the SAME arguments"
        result["retry_directive"] = directive
    return result


SYSTEM_PROMPT = """You are a tech news digest writer.

Workflow you must follow:
1. Call get_headlines for topic "AI agents" (count 5).
2. Write a digest of about 60 words summarizing the headlines.
3. Call slow_publish_article with your digest.
4. If the result contains "retry_directive", follow it EXACTLY: call
   slow_publish_article again with the arguments the directive specifies.
   A retry_directive is a transient backend failure - the publish MUST go through.
5. When the publish succeeds (no retry_directive in the result), output the
   final status text only.

Never reword the article on your own initiative - only when the retry_directive
explicitly tells you to append a suffix."""


model = LiteLLMModel(
    model_id="openai/" + MODEL,
    client_args={
        "base_url": BASE_URL,
        "api_key": "dummy",
        "extra_headers": {"X-Run-Label": RUN_LABEL},
    },
)

t0 = time.time()
agent = Agent(model=model, tools=[get_headlines, slow_publish_article], system_prompt=SYSTEM_PROMPT)
result = agent("Write today's tech news digest and publish it.")
elapsed = time.time() - t0

out_dir = ROOT / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / f"idem_retry_{RUN_LABEL or 'default'}.json").write_text(
    json.dumps(
        {
            "framework": "strands",
            "task": "idem_retry",
            "idem_mode": IDEM_MODE,
            "retry_specs_initial": len(json.loads(os.environ.get("RETRY_SPECS_JSON", "[]"))),
            "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2),
            "n_publish_execs_inproc": len(EXEC_LOG),
            "exec_log": EXEC_LOG,
            "result": str(result)[:400],
        },
        ensure_ascii=False,
        indent=1,
    )
)
print(f"[strands-idem] done in {elapsed:.1f}s ({RUN_LABEL}) publish_execs={len(EXEC_LOG)}")
