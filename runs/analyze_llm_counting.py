"""Analyzer for the counting benchmark (Experiment A) -> artifacts/llm_counting_report.json

Reads runs/manifest_llm_counting.jsonl (408 run records) and the corresponding
traces/llm_calls_<framework>__<label>.jsonl, and scores each run:

  count_correct   : the final answer carries the true count for the question's
                    predicate, validated against the true id set (recomputed
                    from COUNT_SEED/COUNT_SIZE, never from the model's words)
  wrong_count     : the run produced a confident-but-wrong number
  process_error   : the process died / timed out / upstream 4xx-5xx
  no_answer       : the process survived but never emitted a count line
  emission_tokens : completion tokens the model spent to answer (per run)
  survived_mode   : did the "count" tool variant abolish the failure
                    (per-framework x per-mode aggregates)

Also reports the survival split (error / retry / confident wrong) and
tokens-per-question per framework x mode. Run labels carry the framework
prefix so the proxy splits traces per run.

Run: python runs/analyze_llm_counting.py   (after runs/run_llm_counting.py)
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
from parse_sse import parse_sse  # noqa: E402

TRACE_DIR = ROOT / "traces"
MANIFEST = ROOT / "runs" / "manifest_llm_counting.jsonl"

COUNT_NAME_MARKERS = ("get_count_summary", "get_id_list", "count")

ANSWER_RE = re.compile(r"count\s*[=:]\s*(-?\d+)", re.IGNORECASE)
NUMBER_RE = re.compile(r"-?\d+")


def make_ids(n: int, seed: int) -> list:
    rng = random.Random(seed)
    hi = 400 if n > 100 else 50
    return rng.sample(range(1, hi + 1), n)


def true_count(n, seed, lo, hi):
    ids = make_ids(n, seed)
    return len([i for i in ids if (lo is None or i >= lo) and (hi is None or i <= hi)])


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


def extract_answer(text):
    """The count=<number> line (the demanded format); falls back to any number."""
    m = ANSWER_RE.search(text or "")
    if m:
        return int(m.group(1)), "formatted"
    nums = NUMBER_RE.findall(text or "")
    if nums:
        return int(nums[-1]), "bare_number"
    return None, "none"


def analyze_run(rec):
    fw = rec["framework"]
    label = rec["label"]
    path = TRACE_DIR / f"llm_calls_{fw}__{label}.jsonl"
    run = {
        "label": label, "framework": fw, "mode": rec["mode"],
        "qidx": rec["qidx"], "size": rec["size"], "seed": rec["seed"],
        "phrasing": rec["phrasing"], "lo": rec.get("lo"), "hi": rec.get("hi"),
        "question": rec.get("question"),
        "process_ok": rec["ok"], "elapsed_s": rec["elapsed_s"],
        "n_llm_calls": 0, "n_tool_calls": 0, "tokens": 0, "completion_tokens": 0,
        "answer": None, "answer_source": "none", "count_correct": False,
        "outcome": None, "notes": [],
    }
    run["true_count"] = true_count(rec["size"], rec["seed"], rec.get("lo"), rec.get("hi"))
    if not path.exists():
        run["notes"].append("no trace file")
        run["outcome"] = "process_error" if not rec["ok"] else "no_trace"
        return run

    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    run["n_llm_calls"] = len(recs)
    upstream_4xx = any(r.get("status") and 400 <= r["status"] < 500 for r in recs)
    if any(r.get("status") and r["status"] >= 400 for r in recs):
        run["notes"].append("upstream_http_error")
    if upstream_4xx and not rec["ok"]:
        # the run died on an upstream client error (e.g. a 429 quota wall): the
        # process never answered — record as process_error, not no_answer
        run["outcome"] = "process_error"
        run["notes"].append("died_on_upstream_4xx")
        return run

    # walk the calls in order: count tool calls, tokens, and the LAST answer-ish content
    answer_text = ""
    for r in recs:
        p = parsed(r)
        u = p.get("usage") or {}
        run["tokens"] += u.get("total_tokens", 0) or 0
        run["completion_tokens"] += u.get("completion_tokens", 0) or 0
        for tc in p.get("tool_calls") or []:
            if any(m in (tc.get("name") or "") for m in COUNT_NAME_MARKERS):
                run["n_tool_calls"] += 1
        content = (p.get("content") or "").strip()
        if content:
            answer_text = content  # last non-empty model output wins
            if p.get("finish_reason") == "stop":
                run["notes"].append("final_stop_content")

    # outputs/<fw>_result_<label>.json is the framework's own final answer record
    out_file = ROOT / "outputs" / f"{fw}_result_{label}.json"
    if out_file.exists():
        try:
            o = json.loads(out_file.read_text())
            final = o.get("result") or o.get("answer") or ""
            if final:
                answer_text = str(final)
                run["notes"].append("answer_from_output_file")
        except (json.JSONDecodeError, OSError):
            pass

    ans, src = extract_answer(answer_text)
    run["answer"], run["answer_source"] = ans, src
    if ans is None:
        run["outcome"] = "no_answer"
    elif ans == run["true_count"]:
        run["count_correct"] = True
        run["outcome"] = "correct"
    else:
        run["outcome"] = "wrong_count"
    return run


def main():
    manifest = [json.loads(l) for l in MANIFEST.read_text().splitlines() if l.strip()]
    print(f"manifest records: {len(manifest)}")
    # A resume re-run appends the same label again. Two concurrent runners can
    # interleave, so an already-successful label may get a trailing timeout
    # record written after it. Rule: the LAST record that EXITED 0 per label
    # wins (a successful measurement with a trace is never invalidated by a
    # later infrastructure timeout); if a label never exited 0, its last record
    # stands and the run is reported as incomplete.
    grouped = {}
    for rec in manifest:
        grouped.setdefault(rec["label"], []).append(rec)
    by_label = {}
    n_rescued = 0
    for label, recs in grouped.items():
        ok_recs = [r for r in recs if r.get("ok")]
        if ok_recs:
            by_label[label] = ok_recs[-1]
            if recs[-1] is not ok_recs[-1]:
                n_rescued += 1
        else:
            by_label[label] = recs[-1]
    n_dropped = len(manifest) - len(by_label)
    if n_dropped:
        print(f"dedupe: dropped {n_dropped} superseded record(s), {len(by_label)} unique runs")
    if n_rescued:
        print(f"rescued: {n_rescued} label(s) kept their last successful run over a later timeout")
    runs = [analyze_run(rec) for rec in by_label.values()]

    # aggregate per (framework, mode, size)
    agg = {}
    for r in runs:
        agg.setdefault((r["framework"], r["mode"], r["size"]), []).append(r)

    aggregates = {}
    for (fw, mode, size) in sorted(agg, key=lambda k: (k[2] or 0, k[0], k[1])):
        rs = agg[(fw, mode, size)]
        n = len(rs)
        correct = sum(1 for r in rs if r["count_correct"])
        wrong = sum(1 for r in rs if r["outcome"] == "wrong_count")
        errors = sum(1 for r in rs if r["outcome"] == "process_error")
        noans = sum(1 for r in rs if r["outcome"] == "no_answer")
        scored = [r for r in rs if r["outcome"] in ("correct", "wrong_count")]
        aggregates[f"{fw}/{mode}/s{size}"] = {
            "n": n,
            "count_pct": round(100 * correct / n, 1) if n else None,
            "count_pct_of_scored": round(100 * correct / len(scored), 1) if scored else None,
            "correct": correct,
            "wrong_count": wrong,
            "process_error": errors,
            "no_answer": noans,
            # anything neither correct nor a scored wrong count: an exit!=0 run or
            # a label whose trace never landed. Kept as its own column so the row
            # adds up (correct + wrong_count + incomplete == n).
            "incomplete": n - correct - wrong,
            "llm_calls_mean": round(sum(r["n_llm_calls"] for r in rs) / n, 2) if n else None,
            "tool_calls_mean": round(sum(r["n_tool_calls"] for r in rs) / n, 2) if n else None,
            "tokens_mean": round(sum(r["tokens"] for r in rs) / n) if n else None,
            "completion_tokens_mean": round(sum(r["completion_tokens"] for r in rs) / n) if n else None,
            "elapsed_s_mean": round(sum(r["elapsed_s"] for r in rs) / n, 1) if n else None,
        }

    out = {
        "experiment": "A: tool returns rows vs count (framework x mode counting matrix)",
        "modes": {"ids": "model-counts (tool returns only the id list)",
                  "stats": "tool-counts (tool precomputes count/min/max)"},
        "model": "(the same model across all runs - see traces for the exact id)",
        "runs": runs,
        "aggregates": aggregates,
    }
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "llm_counting_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1)
    )
    print("saved -> artifacts/llm_counting_report.json")

    # console score board: per-framework x per-mode x per-size
    print(f"\n{'framework/mode/size':26} {'n':>3} {'count%':>7} {'ofscored':>8} {'wrong':>5} {'err':>4} {'noans':>5} {'incompl':>7}  tokens_mean")
    for key in aggregates:
        a = aggregates[key]
        print(f"{key:26} {a['n']:>3} {str(a['count_pct']):>7} {str(a['count_pct_of_scored']):>8} {a['wrong_count']:>5} "
              f"{a['process_error']:>4} {a['no_answer']:>5} {a['incomplete']:>7}  {a['tokens_mean']}")

    # headline: at size 330, count% in mode A vs mode B, per framework
    print("\nheadline (size 330, count% of ALL runs and of SCORED runs):")
    for fw in sorted({r["framework"] for r in runs}):
        a = aggregates.get(f"{fw}/ids/s330")
        b = aggregates.get(f"{fw}/stats/s330")
        if not a or not b:
            print(f"  {fw:10} incomplete size-330 cells: ids={bool(a)} stats={bool(b)}")
            continue
        print(f"  {fw:10} model-counts={a['count_pct']}% (scored {a['count_pct_of_scored']}%, n={a['n']}, "
              f"incomplete {a['incomplete']})   tool-counts={b['count_pct']}% (scored {b['count_pct_of_scored']}%, n={b['n']})")
        print(f"  {'':10} tokens/question: model-counts={a['tokens_mean']}  tool-counts={b['tokens_mean']}")


if __name__ == "__main__":
    main()
