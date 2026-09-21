"""F: Structured-output compliance analysis.

For each of the 9 recorded runs (3 frameworks x 3 runs), parse the final
output as JSON and check the schema:
  - parses as JSON (strip markdown fences if present)
  - is a JSON object
  - all 4 keys present (summary, word_count, topics, publish_ready)
  - types match (str, int, list, bool)
  - word_count matches the actual summary word count
  - summary is inside the 80-120 band

Also: the validate_output self-check loop in strands (did the model use it,
how many times, did the final output pass its own check).

Output: artifacts/structured_report.json + stdout table.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))

from parse_sse import parse_sse  # noqa: E402

REQUIRED = [("summary", str), ("word_count", int), ("topics", list), ("publish_ready", bool)]


def strip_fences(s):
    s = s.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*?)\n?```\s*$", s, re.DOTALL)
    return m.group(1) if m else s


def check_output(raw_text):
    """Post-run schema check. Returns (ok, violations, parsed)."""
    text = strip_fences(raw_text)
    violations = []
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception as e:
        return False, [f"not valid JSON: {str(e)[:80]}"], None
    if not isinstance(parsed, dict):
        return False, ["not a JSON object"], parsed
    for key, typ in REQUIRED:
        if key not in parsed:
            violations.append(f"missing: {key}")
        elif not isinstance(parsed[key], typ):
            violations.append(f"wrong type {key}: want {typ.__name__} got {type(parsed[key]).__name__}")
    if isinstance(parsed.get("word_count"), int) and isinstance(parsed.get("summary"), str):
        actual = len([w for w in parsed["summary"].split() if w.strip()])
        if parsed["word_count"] != actual:
            violations.append(f"word_count mismatch: claimed {parsed['word_count']} actual {actual}")
        if not (80 <= actual <= 120):
            violations.append(f"summary {actual} words outside band")
    return (not violations), violations, parsed


def validate_loop_count(fw, run):
    """How many times did the model call validate_output (strands only)?"""
    if fw != "strands":
        return None
    p = ROOT / "traces" / f"llm_calls_{fw}__{fw}__structured_run{run}.jsonl"
    if not p.exists():
        return None
    n = 0
    with open(p) as f:
        for l in f:
            rec = json.loads(l)
            raw = (rec.get("response") or {}).get("_raw")
            if raw:
                parsed = parse_sse(raw)
                for t in (parsed.get("tool_calls") or []):
                    if t["name"] == "validate_output":
                        n += 1
    return n


def recover_from_validate_arg(fw, run):
    """Empty-output runs: recover the JSON the model built from the last
    validate_output argument (the model passed its own JSON to the checker
    before finishing empty - the full object is in the tool argument)."""
    if fw != "strands":
        return None
    p = ROOT / "traces" / f"llm_calls_{fw}__{fw}__structured_run{run}.jsonl"
    if not p.exists():
        return None
    last_validate = None
    with open(p) as f:
        for l in f:
            rec = json.loads(l)
            raw = (rec.get("response") or {}).get("_raw")
            if raw:
                parsed = parse_sse(raw)
                for t in (parsed.get("tool_calls") or []):
                    if t["name"] == "validate_output":
                        last_validate = t["arguments"]
    if not last_validate:
        return None
    try:
        args = json.loads(last_validate)
        return json.loads(args.get("output_json", ""))
    except Exception:
        return None


def main():
    rows = {}
    for fw in ["strands", "langgraph", "crewai"]:
        runs = []
        for run in [1, 2, 3]:
            out_f = ROOT / "outputs" / f"{fw}_structured_{fw}__structured_run{run}.json"
            if not out_f.exists():
                runs.append({"run": run, "missing": True})
                continue
            d = json.load(open(out_f))
            ok, violations, parsed = check_output(d.get("result") or "")
            recovered = None
            silent_failure = False
            if not ok and not (d.get("result") or "").strip():
                # empty output - the silent failure mode; recover from the tool arg
                recovered = recover_from_validate_arg(fw, run)
                silent_failure = recovered is not None
                if recovered:
                    ok, violations, parsed = check_output(json.dumps(recovered))
            wc_actual = None
            if parsed and isinstance(parsed.get("summary"), str):
                wc_actual = len([w for w in parsed["summary"].split() if w.strip()])
            runs.append({
                "run": run,
                "json_ok": ok,
                "silent_failure": silent_failure,
                "recovered_from_tool_arg": silent_failure,
                "violations": violations,
                "word_count_actual": wc_actual,
                "word_count_claimed": parsed.get("word_count") if parsed else None,
                "publish_ready": parsed.get("publish_ready") if parsed else None,
                "validate_calls": validate_loop_count(fw, run),
                "elapsed_s": d.get("elapsed_s"),
                "result_head": (d.get("result") or "")[:100],
            })
        ok_runs = [r for r in runs if not r.get("missing")]
        rows[fw] = {
            "runs": runs,
            "compliance_pct": round(100 * sum(1 for r in ok_runs if r["json_ok"]) / len(ok_runs)) if ok_runs else 0,
            "avg_validate_calls": (
                round(sum(r["validate_calls"] for r in ok_runs if r["validate_calls"] is not None) / max(1, sum(1 for r in ok_runs if r["validate_calls"] is not None)), 2)
                if fw == "strands" else None
            ),
        }

    out = ROOT / "artifacts" / "structured_report.json"
    with open(out, "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    print(f"saved: {out}\n")
    for fw, d in rows.items():
        sf = sum(1 for r in d["runs"] if r.get("silent_failure"))
        print(f"=== {fw} === compliance {d['compliance_pct']}%  silent_failures={sf}  avg_validate_calls={d['avg_validate_calls']}")
        for r in d["runs"]:
            if r.get("missing"):
                print(f"  run{r['run']}: MISSING")
                continue
            v = "; ".join(r["violations"]) if r["violations"] else "none"
            sf_tag = " [SILENT-FAIL recovered]" if r.get("silent_failure") else ""
            print(f"  run{r['run']}: ok={r['json_ok']} wc={r['word_count_actual']}(claimed {r['word_count_claimed']}) validate={r['validate_calls']}{sf_tag} violations: {v}")
        print()


if __name__ == "__main__":
    main()
