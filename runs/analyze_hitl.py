"""D (HITL) analysis: how each framework implements the human approval gate.

From 18 recorded runs (3 frameworks x approve/reject x 3 runs) + the proxy traces:
  - LangGraph: framework-level interrupt() + checkpointer. Does the suspension
    fire? What does the resume cost (calls, tokens, latency)?
  - CrewAI: Task(human_input=True) - console-based. How many calls does the
    feedback re-run add? Does the feedback re-enter the conversation?
  - Strands: prompt-level (model-driven). Did the model actually wait for the
    approval? Did it publish without asking, or publish despite rejection?

Also: the traced LLM-call structure per framework/mode (calls, prompt tokens,
latency) - the observability story for the HITL pattern.

Output: artifacts/hitl_report.json + stdout tables.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))

from parse_sse import parse_sse  # noqa: E402


def load(fw, mode, run):
    path = ROOT / "traces" / f"llm_calls_{fw}__{fw}__hitl_{mode}_run{run}.jsonl"
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def norm(lines):
    out = []
    for l in lines:
        u = (l.get("response") or {}).get("usage")
        if not u:
            raw = (l.get("response") or {}).get("_raw")
            u = parse_sse(raw).get("usage") if raw else {}
        out.append({"req": l["request"], "usage": u, "elapsed": l.get("elapsed_s")})
    return out


def tool_sequence(fw, mode, run):
    """Tool calls in response order (SSE) - the model-driven view."""
    lines = load(fw, mode, run)
    seq = []
    for l in lines:
        raw = (l.get("response") or {}).get("_raw")
        if not raw:
            continue
        p = parse_sse(raw)
        for t in (p.get("tool_calls") or []):
            seq.append(t["name"])
    return seq


def analyze_cell(fw, mode):
    cells = []
    for run in [1, 2, 3]:
        n = norm(load(fw, mode, run))
        if not n:
            cells.append({"run": run, "missing": True})
            continue
        calls = len(n)
        pt = sum((x["usage"] or {}).get("prompt_tokens", 0) for x in n)
        ct = sum((x["usage"] or {}).get("completion_tokens", 0) for x in n)
        lat = round(sum(x["elapsed"] or 0 for x in n), 2)
        seq = tool_sequence(fw, mode, run)
        asked = "ask_to_publish" in seq
        published = "publish_article" in seq
        cells.append({
            "run": run,
            "calls": calls,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "latency_s": lat,
            "tool_sequence": seq,
            "asked": asked,
            "published": published,
            # gate compliance: approve-mode must publish AFTER asking; reject must NOT publish
            "gate_ok": (published and asked) if mode == "approve" else (not published),
        })
    ok = [c for c in cells if not c.get("missing")]
    avg = lambda k: round(sum(c[k] for c in ok) / len(ok), 2) if ok else None
    return {
        "runs": cells,
        "avg_calls": avg("calls"),
        "avg_prompt_tokens": avg("prompt_tokens"),
        "avg_completion_tokens": avg("completion_tokens"),
        "avg_latency_s": avg("latency_s"),
        "gate_ok_all": all(c["gate_ok"] for c in ok) if ok else None,
    }


def analyze_langgraph_cell(mode):
    """LangGraph records only the LLM call (write node); HITL state comes from outputs."""
    cells = []
    for run in [1, 2, 3]:
        out_f = ROOT / "outputs" / f"langgraph_hitl_langgraph__hitl_{mode}_run{run}.json"
        if not out_f.exists():
            cells.append({"run": run, "missing": True})
            continue
        d = json.load(open(out_f))
        n = norm(load("langgraph", mode, run))
        cells.append({
            "run": run,
            "calls": len(n),
            "prompt_tokens": sum((x["usage"] or {}).get("prompt_tokens", 0) for x in n),
            "completion_tokens": sum((x["usage"] or {}).get("completion_tokens", 0) for x in n),
            "latency_s": round(sum(x["elapsed"] or 0 for x in n), 2),
            "phase1_s": d.get("phase1_s"),
            "phase2_resume_s": d.get("phase2_resume_s"),
            "interrupted": d.get("interrupted"),
            "approved": d.get("approved"),
            "published": d.get("published"),
            "gate_ok": (d.get("published") is (mode == "approve")) and d.get("interrupted"),
        })
    ok = [c for c in cells if not c.get("missing")]
    avg = lambda k: round(sum(c[k] for c in ok) / len(ok), 2) if ok else None
    return {
        "runs": cells,
        "avg_calls": avg("calls"),
        "avg_prompt_tokens": avg("prompt_tokens"),
        "avg_latency_s": avg("latency_s"),
        "gate_ok_all": all(c["gate_ok"] for c in ok) if ok else None,
        "avg_resume_s": avg("phase2_resume_s"),
    }


def main():
    report = {}
    for fw in ["strands", "crewai"]:
        for mode in ["approve", "reject"]:
            report[f"{fw}:{mode}"] = analyze_cell(fw, mode)
    for mode in ["approve", "reject"]:
        report[f"langgraph:{mode}"] = analyze_langgraph_cell(mode)

    out = ROOT / "artifacts" / "hitl_report.json"
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"saved: {out}\n")
    for key, d in report.items():
        print(f"=== {key} === gate_ok_all={d.get('gate_ok_all')}")
        for c in d["runs"]:
            if c.get("missing"):
                print(f"  run{c['run']}: MISSING")
                continue
            base = f"  run{c['run']}: calls={c['calls']} prompt={c['prompt_tokens']} lat={c['latency_s']}s"
            if "tool_sequence" in c:
                print(f"{base} seq={c['tool_sequence']} gate_ok={c['gate_ok']}")
            else:
                print(f"{base} interrupted={c['interrupted']} approved={c['approved']} published={c['published']} resume={c.get('phase2_resume_s')}s gate_ok={c['gate_ok']}")
        print()


if __name__ == "__main__":
    main()
