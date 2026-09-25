"""Schema-change harshness analysis (Experiment 5, H) -> artifacts/schema_harshness_report.json

Reads runs/manifest_harsh.jsonl (36 run records: ok/elapsed/stderr_tail) and the
corresponding traces/llm_calls_<fw>__<fw>__harsh_<level>_run<N>.jsonl, and scores each run:

  wrong_arg_calls   : model calls to the word-count tool whose arguments do not
                      match the level's expected schema (schema-aware detection,
                      reusing analyze_matrix.py's pattern: read the schema the
                      framework actually exposed, check the args the model sent).
  schema_errors_seen : how many DISTINCT tool_call ids got an error response from
                      the tool layer (validation failures / JSON parse failures /
                      missing required args), deduped by tool_call_id because
                      strands accumulates message history across requests.
  recovery           : adapted_within_run = at least one schema-VALID word-count
                      call AFTER the first wrong/error one (the model corrected
                      itself inside the run); fail_stop = process died;
                      no_error = no schema mismatch ever occurred.
  silent_failure     : process exited 0 but the draft was never really verified
                      (word_count never successfully called with valid args) --
                      for remove-level, a "valid" call still returns the static
                      placeholder, so it counts as never-verified.
  final_words        : the word count of the last digest-looking model output
                      (finish_reason=stop, >80 chars) -- whether verification
                      actually happened is the verified column.

Run: python runs/analyze_harsh.py   (after runs/run_harsh.py)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
from parse_sse import parse_sse  # noqa: E402

TRACE_DIR = ROOT / "traces"
MANIFEST = ROOT / "runs" / "manifest_harsh.jsonl"
LEVELS = ["rename", "type", "remove", "add"]

WC_NAME_MARKERS = ("count", "word_count")  # strands: check_word_count, crewai: count_words, lg: n/a


def parsed(r):
    resp = r["response"]
    if "_raw" in resp:
        return parse_sse(resp["_raw"])
    if "choices" in resp:
        msg = resp["choices"][0]["message"]
        return {
            "content": msg.get("content") or "",
            "tool_calls": [
                {"id": t["id"], "name": t["function"]["name"], "arguments": t["function"]["arguments"]}
                for t in (msg.get("tool_calls") or [])
            ],
            "finish_reason": resp["choices"][0].get("finish_reason"),
            "usage": resp.get("usage"),
        }
    return {"content": "", "tool_calls": [], "finish_reason": None, "usage": None}


def is_wc_tool(name):
    return any(m in (name or "") for m in WC_NAME_MARKERS) and "headline" not in (name or "")


def wc_schema_in(rec):
    """The word-count tool schema this run's framework actually exposed."""
    for t in rec["request"].get("tools", []):
        name = (t.get("function") or {}).get("name", "")
        if is_wc_tool(name):
            fn = t["function"]
            return {
                "name": name,
                "properties": (fn.get("parameters") or {}).get("properties", {}),
                "required": (fn.get("parameters") or {}).get("required", []),
            }
    return None


def args_match_schema(args, schema, level):
    """Schema-aware validation of the model's word-count call args."""
    if schema is None:
        return None  # langgraph: tools are code-invoked, no schema on the wire
    props = schema["properties"]
    req = set(schema["required"])
    keys = set(args.keys())
    if keys != set(props.keys()):
        # extra keys (prompt's old name) or missing required keys
        if keys - set(props.keys()) or req - keys:
            return False
    # type check the expected params
    for k, spec in props.items():
        if k in args:
            want = spec.get("type")
            got = args[k]
            if want == "string" and not isinstance(got, str):
                return False
            if want == "integer" and (isinstance(got, bool) or not isinstance(got, int)):
                return False
            if want == "number" and (isinstance(got, bool) or not isinstance(got, (int, float))):
                return False
    return True


def analyze_run(label, manifest_rec):
    fw = manifest_rec["framework"]
    level = manifest_rec["harsh_level"]
    path = TRACE_DIR / f"llm_calls_{fw}__{label}.jsonl"
    run = {
        "label": label, "framework": fw, "harsh_level": level, "run": manifest_rec["run"],
        "process_ok": manifest_rec["ok"], "elapsed_s": manifest_rec["elapsed_s"],
        "n_llm_calls": 0, "tokens": 0,
        "wc_calls": 0, "wrong_arg_calls": 0, "schema_errors_seen": 0,
        "tool_error_responses": 0,
        "valid_wc_calls": 0, "recovery": None, "silent_failure": None,
        "wc_results": [], "final_words": None, "verified": False,
        "error_kinds": [], "notes": [],
    }
    if not path.exists():
        run["notes"].append("no trace file")
        run["recovery"] = "no_trace"
        run["silent_failure"] = None
        return run

    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    run["n_llm_calls"] = len(recs)

    # tool responses keyed by tool_call_id, deduped across accumulating histories
    tool_results = {}
    error_ids = set()
    for r in recs:
        for m in r["request"].get("messages", []):
            if m.get("role") != "tool":
                continue
            c = m.get("content") or ""
            tid = m.get("tool_call_id")
            tname = m.get("name") or ""
            if tid and tid not in tool_results:
                tool_results[tid] = c
            is_err = c.startswith("Error") or "Validation failed" in c or "Failed to parse tool arguments" in c
            if is_err and tid:
                error_ids.add(tid)

    # walk the calls in order
    first_bad_idx = None
    schema = None
    schema_seen = False
    wc_events = []  # (call_index, valid?)
    wc_valid_content = []
    wc_call_ids = []  # tool_call ids in call order
    for i, r in enumerate(recs):
        if schema is None:
            schema = wc_schema_in(r)
            schema_seen = schema is not None
        p = parsed(r)
        run["tokens"] += (p.get("usage") or {}).get("total_tokens", 0) or 0
        for tc in p.get("tool_calls") or []:
            if not is_wc_tool(tc.get("name", "")):
                continue
            run["wc_calls"] += 1
            wc_call_ids.append(tc.get("id"))
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = None
                run["wrong_arg_calls"] += 1
                run["error_kinds"].append("unparseable_json")
                wc_events.append((run["wc_calls"], False))
                if first_bad_idx is None:
                    first_bad_idx = run["wc_calls"]
                continue
            ok = args_match_schema(args, schema, level)
            if ok is False and schema is not None:
                run["wrong_arg_calls"] += 1
                kind = "missing_required" if set(schema["required"]) - set(args) else "unexpected_keys"
                run["error_kinds"].append(kind)
            elif ok is None:
                # langgraph: no schema on the wire; code-invoked. If the process
                # died, the crash IS the wrong-arg event.
                pass
            wc_events.append((run["wc_calls"], bool(ok)))
            if ok:
                run["valid_wc_calls"] += 1
                for k in ("content", "text"):
                    if isinstance(args.get(k), str):
                        wc_valid_content.append(args[k])
            if first_bad_idx is None and ok is False:
                first_bad_idx = run["wc_calls"]

    # successful (non-error) tool results that carry a word_count
    errored_call_ids = set()  # wc calls whose result was an error (schema OR app-level)
    for tid, c in tool_results.items():
        d = None
        try:
            d = json.loads(c)
        except (json.JSONDecodeError, TypeError):
            # crewai stringifies tool results with Python repr (single quotes)
            try:
                import ast

                d = ast.literal_eval(c)
            except (ValueError, SyntaxError, TypeError):
                d = None
        if isinstance(d, dict) and "word_count" in d:
            run["wc_results"].append(d["word_count"])
        elif isinstance(d, dict) and "error" in d:
            # schema-valid call, application-level error (e.g. document id not found)
            run["tool_error_responses"] += 1
            errored_call_ids.add(tid)
        elif isinstance(d, dict) and "char_count" in d and "word_count" not in d:
            run["wc_results"].append(None)

    # langgraph: tools are code-invoked, so the wire carries no tool traffic.
    # Verification evidence lives in the output JSON the graph writes on success.
    code_verified = False
    if fw == "langgraph":
        out_file = ROOT / "outputs" / f"langgraph_result_{label}.json"
        if out_file.exists():
            try:
                o = json.loads(out_file.read_text())
                wc = o.get("word_count")
                if isinstance(wc, int) and wc > 0:
                    run["wc_results"].append(wc)
                    run["final_words"] = wc
                    code_verified = True
                    run["notes"].append("langgraph: tool invoked in code; verified from output file")
            except (json.JSONDecodeError, OSError):
                pass

    run["schema_errors_seen"] = len(error_ids & {t for t in tool_results}) if tool_results else 0
    # error_ids may reference ids whose results we keyed; count directly
    run["schema_errors_seen"] = len(error_ids)

    # final digest-looking output
    last_content = ""
    for r in recs:
        p = parsed(r)
        content = (p.get("content") or "").strip()
        if content and len(content) > 80 and p.get("finish_reason") == "stop":
            last_content = content
    run["final_words"] = len([w for w in last_content.split() if w.strip()]) if last_content else None

    # verified = word_count successfully called with schema-valid args AND a
    # real count came back. remove-level's static 8/49 never counts: a schema-
    # valid call there still didn't verify the draft.
    real_results = [w for w in run["wc_results"] if isinstance(w, int)]
    if level == "remove":
        verified = False  # by construction the draft is never actually counted
        run["notes"].append("remove: static count returned, draft never verified")
    else:
        verified = code_verified or (run["valid_wc_calls"] > 0 and len(real_results) > 0)
    run["verified"] = verified

    # recovery classification
    if not run["process_ok"] and run["recovery"] != "no_trace":
        # process died (crash / timeout / upstream 400) -> the run STOPPED
        run["recovery"] = "fail_stop"
    else:
        # any wc call that errored at the tool layer (schema rejection OR
        # app-level error like "document not found") is a recovery-relevant
        # event; recovery = a later call that SUCCEEDED (real count returned)
        first_bad_idx2 = first_bad_idx
        later_success = []
        for n, (idx, ok) in enumerate(wc_events):
            tid = wc_call_ids[n] if n < len(wc_call_ids) else None
            succeeded = ok and tid not in errored_call_ids
            if first_bad_idx2 is None and not succeeded:
                first_bad_idx2 = idx
            if first_bad_idx2 is not None and idx > first_bad_idx2 and succeeded:
                later_success.append(idx)
        if first_bad_idx2 is None and not error_ids:
            run["recovery"] = "no_error"  # nothing to recover from
        elif later_success:
            run["recovery"] = "adapted_within_run"
        else:
            run["recovery"] = "gave_up_within_run"

    # silent failure: exit 0 but never actually verified
    run["silent_failure"] = bool(run["process_ok"] and not verified)

    return run


def main():
    manifest = [json.loads(l) for l in MANIFEST.read_text().splitlines() if l.strip()]
    print(f"manifest records: {len(manifest)}")
    runs = []
    for rec in manifest:
        runs.append(analyze_run(rec["label"], rec))

    # aggregate per (framework, level)
    agg = {}
    for r in runs:
        agg.setdefault((r["framework"], r["harsh_level"]), []).append(r)

    aggregates = {}
    for (fw, level) in sorted(agg, key=lambda k: (k[1], k[0])):
        rs = agg[(fw, level)]
        n = len(rs)
        ok = sum(1 for r in rs if r["process_ok"])
        verified = sum(1 for r in rs if r["verified"])
        silent = sum(1 for r in rs if r["silent_failure"])
        recovers = [r["recovery"] for r in rs]
        aggregates[f"{fw}/{level}"] = {
            "n": n,
            "process_ok": ok,
            "verified": verified,
            "silent_failure": silent,
            "wrong_arg_calls_total": sum(r["wrong_arg_calls"] for r in rs),
            "schema_errors_total": sum(r["schema_errors_seen"] for r in rs),
            "tool_error_responses_total": sum(r["tool_error_responses"] for r in rs),
            "wc_calls_mean": round(sum(r["wc_calls"] for r in rs) / n, 2),
            "llm_calls": [r["n_llm_calls"] for r in rs],
            "tokens_mean": round(sum(r["tokens"] for r in rs) / n),
            "recovery": {k: recovers.count(k) for k in sorted(set(recovers))},
            "final_words": [r["final_words"] for r in rs],
            "elapsed_s": [r["elapsed_s"] for r in rs],
        }

    out = {
        "experiment": "H: schema-change harshness ladder",
        "levels": LEVELS,
        "level_meanings": {
            "rename": "word_count(content: str) - arg renamed, prompts still say text",
            "type": "word_count(content: int) - arg TYPE changed to a document id",
            "remove": "word_count() - the text arg deleted; tool returns a static count",
            "add": "word_count(content: str, note: str) - new required arg the prompts never mention",
        },
        "model": "(the same model across all runs - see traces for the exact id)",
        "runs": runs,
        "aggregates": aggregates,
    }
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "schema_harshness_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1)
    )
    print("saved -> artifacts/schema_harshness_report.json")

    # console summary
    print(f"\n{'framework/level':22} {'ok':>3} {'verif':>5} {'silent':>6} {'wrong':>5} {'err':>4}  recovery")
    for key in aggregates:
        a = aggregates[key]
        print(f"{key:22} {a['process_ok']:>3} {a['verified']:>5} {a['silent_failure']:>6} "
              f"{a['wrong_arg_calls_total']:>5} {a['schema_errors_total']:>4}  {a['recovery']}")


if __name__ == "__main__":
    main()
