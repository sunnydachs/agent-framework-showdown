"""E: Audit-trail reconstruction - what an auditor can recover from each framework.

The compliance question (from r/LangChain, r/mlops, EU AI Act Art. 12):
"WHY did the agent make this decision - and can you prove it six months later?"

For every recorded run (base 27 + complex 9 + hitl 18 = 54 runs), extract the
audit-relevant facts from the proxy traces and score whether each framework's
traces can answer them:
  1. decision_rationale: the reasoning the model produced (why it acted)
  2. tool_call_order: the exact sequence of tool calls with arguments
  3. model_identity: which model/provider actually served the call
  4. schema_expectation: what tool schema the model was shown (drift forensics)
  5. full_context: the complete message history (what the model saw)
  6. empty_output_detection: silent failures (content='' with finish_reason=stop)
  7. token_cost: usage per call (reproducible cost accounting)

All of this comes from the SAME trace shape (the recorder proxy's JSONL) -
which is the point: one proxy in front of every framework makes the audit
trail comparable.

Output: artifacts/audit_report.json + stdout table.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))

from parse_sse import parse_sse  # noqa: E402

TRACE_DIR = ROOT / "traces"


def load_run(fw, task, run):
    """Return the trace lines for a run, or [] if missing."""
    if task == "hitl":
        # hitl has 6 runs per fw: run1-3 = approve, run4-6 = reject
        mode = "approve" if run <= 3 else "reject"
        p = TRACE_DIR / f"llm_calls_{fw}__{fw}__hitl_{mode}_run{run if run <= 3 else run - 3}.jsonl"
        if p.exists():
            with open(p) as f:
                return [json.loads(l) for l in f if l.strip()]
        return []
    p = TRACE_DIR / f"llm_calls_{fw}__{fw}__{task}_run{run}.jsonl"
    if not p.exists():
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def get_parsed(rec):
    resp = rec.get("response") or {}
    if "_raw" in resp:
        return parse_sse(resp["_raw"])
    if "choices" in resp:
        msg = resp["choices"][0].get("message", {})
        return {
            "content": msg.get("content") or "",
            "tool_calls": [
                {"id": t["id"], "name": t["function"]["name"], "arguments": t["function"]["arguments"]}
                for t in (msg.get("tool_calls") or [])
            ],
            "reasoning": msg.get("reasoning") or "",
            "finish_reason": resp["choices"][0].get("finish_reason"),
            "usage": resp.get("usage"),
            "model": resp.get("model"),
            "provider": resp.get("provider"),
        }
    return None


def audit_run(fw, task, run):
    lines = load_run(fw, task, run)
    if not lines:
        return None
    parsed = [get_parsed(l) for l in lines]
    parsed = [p for p in parsed if p]

    reasoning_total = sum(len(p.get("reasoning") or "") for p in parsed)
    tool_calls = []
    for p in parsed:
        for t in (p.get("tool_calls") or []):
            args = t.get("arguments")
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except Exception:
                pass
            tool_calls.append({"name": t.get("name"), "args": args})
    models = {p.get("model") for p in parsed if p.get("model")}
    providers = {p.get("provider") for p in parsed if p.get("provider")}
    # schema expectation: tool schemas in the request (first call)
    first_req = lines[0].get("request") or {}
    schemas = {t["function"]["name"]: list((t["function"].get("parameters") or {}).get("properties", {}).keys())
               for t in (first_req.get("tools") or []) if "function" in t}
    # full context: message count + total chars in the last call
    last_req = lines[-1].get("request") or {}
    msgs = last_req.get("messages") or []
    ctx_chars = sum(len(m.get("content") or "") if isinstance(m.get("content"), str) else len(json.dumps(m.get("content"))) for m in msgs)
    # silent failure: final call with empty content AND finish=stop
    silent_fail = False
    if parsed:
        last = parsed[-1]
        silent_fail = (last.get("content") or "") == "" and last.get("finish_reason") == "stop" and not (last.get("tool_calls"))
    usage = [(p.get("usage") or {}).get("prompt_tokens", 0) for p in parsed]

    return {
        "framework": fw,
        "task": task,
        "run": run,
        "n_calls": len(lines),
        "decision_rationale_chars": reasoning_total,
        "tool_call_order": [t["name"] for t in tool_calls],
        "tool_args_recoverable": all(t.get("args") is not None for t in tool_calls) if tool_calls else None,
        "model_identity": sorted(models),
        "provider_identity": sorted(providers),
        "schema_expectation": schemas,
        "full_context_chars": ctx_chars,
        "silent_failure": silent_fail,
        "prompt_tokens": usage,
    }


def main():
    runs = []
    for task in ["base", "complex", "hitl"]:
        n = 3 if task != "hitl" else 6  # hitl: 6 runs per fw (3 approve + 3 reject)
        for fw in ["strands", "langgraph", "crewai"]:
            for run in range(1, n + 1):
                a = audit_run(fw, task, run)
                if a:
                    runs.append(a)

    # Aggregate per framework: what fraction of runs can answer each audit question
    agg = {}
    for fw in ["strands", "langgraph", "crewai"]:
        fw_runs = [r for r in runs if r["framework"] == fw]
        n = len(fw_runs)
        agg[fw] = {
            "n_runs": n,
            "n_calls_total": sum(r["n_calls"] for r in fw_runs),
            "rationale_available_pct": round(100 * sum(1 for r in fw_runs if r["decision_rationale_chars"] > 0) / n) if n else 0,
            "tool_order_available_pct": round(100 * sum(1 for r in fw_runs if r["tool_call_order"]) / n) if n else 0,
            "args_recoverable_pct": round(100 * sum(1 for r in fw_runs if r["tool_args_recoverable"]) / n) if n else 0,
            "model_identity_pct": round(100 * sum(1 for r in fw_runs if r["model_identity"]) / n) if n else 0,
            "schema_recorded_pct": round(100 * sum(1 for r in fw_runs if r["schema_expectation"]) / n) if n else 0,
            "silent_failures": sum(1 for r in fw_runs if r["silent_failure"]),
            "silent_failure_runs": [f"{r['task']}_run{r['run']}" for r in fw_runs if r["silent_failure"]],
            "avg_context_chars_last_call": round(sum(r["full_context_chars"] for r in fw_runs) / n) if n else 0,
        }

    out = ROOT / "artifacts" / "audit_report.json"
    with open(out, "w") as f:
        json.dump({"per_run": runs, "per_framework": agg}, f, ensure_ascii=False, indent=1)

    print(f"saved: {out}\n")
    print(f"{'framework':10s} {'runs':>5s} {'calls':>6s} {'rationale%':>10s} {'tool_ord%':>10s} {'args%':>10s} {'model%':>7s} {'schema%':>8s} {'silentFAIL':>10s}")
    for fw, a in agg.items():
        print(f"{fw:10s} {a['n_runs']:5d} {a['n_calls_total']:6d} {a['rationale_available_pct']:10d} {a['tool_order_available_pct']:10d} {a['args_recoverable_pct']:10d} {a['model_identity_pct']:7d} {a['schema_recorded_pct']:8d} {a['silent_failures']:10d}")

    print("\nsilent failure runs (empty content, finish=stop, exit 0):")
    for fw, a in agg.items():
        if a["silent_failure_runs"]:
            print(f"  {fw}: {', '.join(a['silent_failure_runs'])}")

    print("\nsample audit record (strands, complex, run2 - the silent failure):")
    sample = next((r for r in runs if r["framework"] == "strands" and r["task"] == "complex" and r["run"] == 2), None)
    if sample:
        print(json.dumps(sample, indent=1, ensure_ascii=False)[:800])


if __name__ == "__main__":
    main()
