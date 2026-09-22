"""Analysis for Experiment 4: crash recovery + idempotency + audit-under-retry.

Cells:
  A (crash-resume): resume latency + state survival per framework/checkpointer;
     the issue-8764 shape (crash before first durable checkpoint) and the
     failure-record gap; CrewAI @persist probe (what it stores vs what a
     killed crew run loses).
  B (idempotency): duplicate executions per key strategy (position vs
     content-hash vs none) x retry shape (same-args vs reworded), distinct
     tool_call_ids on the wire, ledger dedup correctness. The tianpan.co
     claim: an LLM retry reasons again and emits a NEW call - a content-hash
     key misses dedup when args get reworded.
  C (audit-under-retry): per-run audit facts from the proxy traces ALONE
     (the same shape as analyze_audit.py's 7 facts) + the 8th fact -
     dedup_detection: can an auditor detect the duplicate publish from the
     traces alone, and does the trace prove execution or only intent?

Output: artifacts/crash_idem_report.json + stdout tables.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))

from parse_sse import parse_sse  # noqa: E402

TRACE_DIR = ROOT / "traces"
OUT_DIR = ROOT / "outputs"


def load_trace(label):
    fw = label.split("__", 1)[0]
    p = TRACE_DIR / f"llm_calls_{fw}__{label}.jsonl"
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


def tool_calls_in_trace(lines, tool_name=None):
    """All tool calls across the run's responses, in order (id, name, args)."""
    out = []
    for l in lines:
        p = get_parsed(l)
        if not p:
            continue
        for t in p.get("tool_calls") or []:
            if tool_name and t.get("name") != tool_name:
                continue
            try:
                args = json.loads(t.get("arguments")) if isinstance(t.get("arguments"), str) else t.get("arguments")
            except Exception:
                args = t.get("arguments")
            out.append({"id": t.get("id"), "name": t.get("name"), "args": args})
    return out


# ----------------------------------------------------------------- Cell A ----
def analyze_cell_a():
    a = {"langgraph": {}, "strands": {}, "crewai": {}}

    # langgraph: durable vs mem checkpointer
    for shape in ["durable", "mem"]:
        runs = []
        for run in [1, 2, 3]:
            p = OUT_DIR / f"langgraph_crash_langgraph__crash_{shape}_run{run}__resume.json"
            p1 = OUT_DIR / f"langgraph_crash_langgraph__crash_{shape}_run{run}__phase1.json"
            if not p.exists():
                continue
            d = json.load(open(p))
            d1 = json.load(open(p1)) if p1.exists() else {}
            # crash-resume audit: how many LLM calls did the RESUME cost?
            tr = load_trace(f"langgraph__crash_{shape}_run{run}")
            # timestamps: phase1 writes the first call; resume writes any after
            runs.append({
                "run": run,
                "phase1_s": d1.get("phase1_s"),
                "resume_s": d.get("resume_s"),
                "state_survived": d.get("state_survived"),
                "published": d.get("published"),
                "llm_calls_total": len(tr),
                "llm_calls_resume_side": max(0, len(tr) - 1),  # 1 call in phase1 (write_draft)
            })
        ok = [r for r in runs if r]
        avg = lambda k: round(sum(r[k] for r in ok if r.get(k) is not None) / max(1, len([r for r in ok if r.get(k) is not None])), 2) if ok else None
        a["langgraph"][shape] = {
            "runs": runs,
            "n": len(runs),
            "avg_phase1_s": avg("phase1_s"),
            "avg_resume_s": avg("resume_s"),
            "state_survived_all": all(r["state_survived"] for r in ok) if ok else None,
            "published_all": all(r["published"] for r in ok) if ok else None,
            "resume_llm_calls_avg": avg("llm_calls_resume_side"),
        }

    # strands / crewai: full re-run (no state to resume from)
    for fw in ["strands", "crewai"]:
        runs = []
        for run in [1, 2, 3]:
            p = OUT_DIR / f"{fw}_crash_{fw}__crash_noresume_run{run}__resume.json"
            if not p.exists():
                continue
            d = json.load(open(p))
            tr = load_trace(f"{fw}__crash_noresume_run{run}")
            runs.append({
                "run": run,
                "resume_s": d.get("resume_s"),
                "rerun": d.get("rerun"),
                "resume_error": d.get("resume_error") or d.get("crew_error"),
                "fallback_fresh_s": d.get("fallback_fresh_s"),
                "llm_calls_total": len(tr),
            })
        ok = [r for r in runs if r]
        avg = lambda k: round(sum(r[k] for r in ok if r.get(k) is not None) / max(1, len([r for r in ok if r.get(k) is not None])), 2) if ok else None
        a[fw] = {
            "runs": runs,
            "n": len(runs),
            "avg_resume_s": avg("resume_s"),
            "avg_llm_calls_rerun": avg("llm_calls_total"),
            "fallback_needed_runs": sum(1 for r in ok if r.get("resume_error")),
        }

    # issue-8764 reproduction (3 runs)
    reps = []
    for run in [1, 2, 3]:
        p = OUT_DIR / f"langgraph_crash_langgraph__crash_8764_run{run}__8764.json"
        if p.exists():
            reps.append(json.load(open(p)))
    a["issue_8764"] = {
        "n": len(reps),
        "empty_input_error_raised": any(
            "EmptyInputError" in json.dumps(r) for r in reps
        ),
        "behavior": reps[0].get("failure_record_gap") if reps else None,
        "llm_calls_incurred_by_empty_resume": [r.get("llm_calls_incurred_by_empty_resume") for r in reps],
        "sample_errors": {k: v for k, v in reps[0].items() if k.endswith("error") or "resume" in k} if reps else None,
    }

    # crewai @persist probe
    p = OUT_DIR / "crewai_crash_crewai__crash_persist_probe__persist.json"
    a["crewai_persist_probe"] = json.load(open(p)) if p.exists() else None
    return a


# ----------------------------------------------------------------- Cell B ----
def analyze_cell_b():
    modes = ["position", "hash", "none"]
    shapes = ["same", "reworded"]
    b = {}
    for mode in modes:
        for shape in shapes:
            runs = []
            for run in [1, 2, 3]:
                label = f"strands__idem_{mode}_{shape}_run{run}"
                p = OUT_DIR / f"idem_retry_{label}.json"
                if not p.exists():
                    continue
                d = json.load(open(p))
                exec_log = d.get("exec_log") or []
                n_exec = len(exec_log)
                n_dup = max(0, n_exec - 1)  # first exec is the legitimate one
                n_deduped = sum(1 for e in exec_log if (e.get("result") or {}).get("deduped"))
                n_caller_bug = sum(1 for e in exec_log if e.get("error") and "caller bug" in e["error"].lower())
                # ledger state: what the auditor reads from the ledger file
                ledger_p = TRACE_DIR / "idem" / f"idem_ledger_{label}.sqlite"
                ledger_rows = None
                if ledger_p.exists():
                    try:
                        conn = sqlite3.connect(str(ledger_p))
                        ledger_rows = conn.execute(
                            "SELECT key, tool_name, status, parameter_hash FROM idempotency"
                        ).fetchall()
                        conn.close()
                    except Exception as e:
                        ledger_rows = f"read_error: {e}"
                # wire view: distinct tool_call_ids for the publish tool
                tr = load_trace(label)
                pubs = tool_calls_in_trace(tr, "slow_publish_article")
                runs.append({
                    "run": run,
                    "n_publish_execs": n_exec,
                    "n_duplicate_execs": n_dup,
                    "n_deduped_returns": n_deduped,
                    "n_caller_bug_rejects": n_caller_bug,
                    "n_publish_calls_on_wire": len(pubs),
                    "distinct_tool_call_ids_on_wire": len({t["id"] for t in pubs}),
                    "ledger_rows": ledger_rows,
                })
            ok = [r for r in runs if r]
            avg = lambda k: round(sum(r[k] for r in ok) / len(ok), 2) if ok else None
            b[f"{mode}:{shape}"] = {
                "runs": runs,
                "n": len(ok),
                "avg_publish_execs": avg("n_publish_execs"),
                "avg_duplicate_execs": avg("n_duplicate_execs"),
                "avg_deduped_returns": avg("n_deduped_returns"),
                "avg_caller_bug_rejects": avg("n_caller_bug_rejects"),
                "avg_publish_calls_on_wire": avg("n_publish_calls_on_wire"),
                "avg_distinct_tool_call_ids": avg("distinct_tool_call_ids_on_wire"),
            }
    return b


# ----------------------------------------------------------------- Cell C ----
def audit_idem_run(mode, shape, run):
    """The 8 audit facts for one idem run, from the proxy trace ALONE."""
    label = f"strands__idem_{mode}_{shape}_run{run}"
    lines = load_trace(label)
    if not lines:
        return None
    parsed = [get_parsed(l) for l in lines]
    parsed = [p for p in parsed if p]

    reasoning_total = sum(len(p.get("reasoning") or "") for p in parsed)
    all_tools = tool_calls_in_trace(lines)
    pubs = tool_calls_in_trace(lines, "slow_publish_article")
    models = {p.get("model") for p in parsed if p.get("model")}
    first_req = lines[0].get("request") or {}
    schemas = {
        t["function"]["name"]: list((t["function"].get("parameters") or {}).get("properties", {}).keys())
        for t in (first_req.get("tools") or []) if "function" in t
    }
    last_req = lines[-1].get("request") or {}
    msgs = last_req.get("messages") or []
    ctx_chars = sum(len(m.get("content") or "") if isinstance(m.get("content"), str) else len(json.dumps(m.get("content"))) for m in msgs)
    usage = [(p.get("usage") or {}).get("prompt_tokens", 0) for p in parsed]

    # the retry evidence: does the tool result with retry_directive re-enter
    # the conversation (visible in a later request)?
    retry_directive_visible = any("retry_directive" in json.dumps(m.get("content") or "")[:2000] for m in msgs)

    # THE 8TH FACT - dedup detection from the trace alone
    pub_args = [t["args"] for t in pubs if isinstance(t.get("args"), dict)]
    articles = [a.get("article") or "" for a in pub_args]
    args_identical = len(articles) >= 2 and articles[0] == articles[-1]
    duplicate_call_visible = len(pubs) >= 2
    distinct_ids = len({t["id"] for t in pubs})

    # execution truth (from the in-process exec log - NOT the trace)
    p = OUT_DIR / f"idem_retry_{label}.json"
    d = json.load(open(p)) if p.exists() else {}
    exec_log = d.get("exec_log") or []
    actual_execs = len(exec_log)

    dedup_detection = {
        "duplicate_call_visible_in_trace": duplicate_call_visible,
        "n_publish_calls_on_wire": len(pubs),
        "distinct_tool_call_ids": distinct_ids,
        "args_identical_across_attempts": args_identical,
        "retry_directive_visible_in_context": retry_directive_visible,
        "trace_proves": "intent (the model emitted N calls)" if len(pubs) > actual_execs else "execution (call count == exec count)",
        "actual_executions": actual_execs,
        "execution_proof_source": "trace" if actual_execs == len(pubs) and not any((e.get("result") or {}).get("deduped") for e in exec_log) else "ledger/exec-log required",
        "auditor_can_detect_duplicate": duplicate_call_visible,
        "auditor_can_prove_dedup_from_trace_alone": False if mode != "none" and len(pubs) != actual_execs else (len(pubs) == actual_execs),
    }

    return {
        "label": label,
        "framework": "strands",
        "mode": mode,
        "shape": shape,
        "run": run,
        "n_calls": len(lines),
        "decision_rationale_chars": reasoning_total,
        "tool_call_order": [t["name"] for t in all_tools],
        "model_identity": sorted(models),
        "schema_expectation": schemas,
        "full_context_chars_last_call": ctx_chars,
        "empty_output_silent_failure": bool(parsed) and (parsed[-1].get("content") or "") == "" and parsed[-1].get("finish_reason") == "stop" and not parsed[-1].get("tool_calls"),
        "prompt_tokens": usage,
        "dedup_detection": dedup_detection,
    }


def analyze_cell_c():
    c = {}
    for mode in ["position", "hash", "none"]:
        for shape in ["same", "reworded"]:
            runs = [audit_idem_run(mode, shape, r) for r in [1, 2, 3]]
            runs = [r for r in runs if r]
            if not runs:
                continue
            c[f"{mode}:{shape}"] = {
                "n": len(runs),
                "rationale_available_pct": round(100 * sum(1 for r in runs if r["decision_rationale_chars"] > 0) / len(runs)),
                "tool_order_available_pct": round(100 * sum(1 for r in runs if r["tool_call_order"]) / len(runs)),
                "retry_directive_visible_pct": round(100 * sum(1 for r in runs if r["dedup_detection"]["retry_directive_visible_in_context"]) / len(runs)),
                "duplicate_detectable_pct": round(100 * sum(1 for r in runs if r["dedup_detection"]["auditor_can_detect_duplicate"]) / len(runs)),
                "dedup_provable_from_trace_alone_pct": round(100 * sum(1 for r in runs if r["dedup_detection"]["auditor_can_prove_dedup_from_trace_alone"]) / len(runs)),
                "args_identical_pct": round(100 * sum(1 for r in runs if r["dedup_detection"]["args_identical_across_attempts"]) / len(runs)),
                "runs": runs,
            }
    return c


def main():
    report = {
        "experiment": 4,
        "title": "crash recovery + idempotency + audit-under-retry",
        "cell_a_crash_resume": analyze_cell_a(),
        "cell_b_idempotency": analyze_cell_b(),
        "cell_c_audit_under_retry": analyze_cell_c(),
    }
    out = ROOT / "artifacts" / "crash_idem_report.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"saved: {out}\n")

    print("=== CELL A: crash-resume ===")
    for shape in ["durable", "mem"]:
        d = report["cell_a_crash_resume"]["langgraph"][shape]
        print(f"  langgraph/{shape:7s}: resume={d['avg_resume_s']}s survived={d['state_survived_all']} published={d['published_all']} resume_llm_calls={d['resume_llm_calls_avg']}")
    for fw in ["strands", "crewai"]:
        d = report["cell_a_crash_resume"][fw]
        print(f"  {fw:10s}: full-rerun={d['avg_resume_s']}s llm_calls={d['avg_llm_calls_rerun']} fallback_needed={d['fallback_needed_runs']}")
    i = report["cell_a_crash_resume"]["issue_8764"]
    print(f"  issue-8764: EmptyInputError={i['empty_input_error_raised']} | {i['behavior']}")
    print(f"  crewai @persist: {json.dumps(report['cell_a_crash_resume']['crewai_persist_probe'], default=str)[:150]}")

    print("\n=== CELL B: idempotency (avg over 3 runs) ===")
    print(f"  {'mode:shape':18s} {'execs':>6s} {'dups':>5s} {'deduped':>8s} {'caller_bug':>10s} {'wire_calls':>10s} {'distinct_ids':>12s}")
    for k, d in report["cell_b_idempotency"].items():
        print(f"  {k:18s} {d['avg_publish_execs']:6} {d['avg_duplicate_execs']:5} {d['avg_deduped_returns']:8} {d['avg_caller_bug_rejects']:10} {d['avg_publish_calls_on_wire']:10} {d['avg_distinct_tool_call_ids']:12}")

    print("\n=== CELL C: audit-under-retry (trace-only auditor) ===")
    print(f"  {'mode:shape':18s} {'rationale%':>10s} {'dup_visible%':>13s} {'dedup_provable%':>15s} {'retry_evidence%':>15s}")
    for k, d in report["cell_c_audit_under_retry"].items():
        print(f"  {k:18s} {d['rationale_available_pct']:10} {d['duplicate_detectable_pct']:13} {d['dedup_provable_from_trace_alone_pct']:15} {d['retry_directive_visible_pct']:15}")


if __name__ == "__main__":
    main()
