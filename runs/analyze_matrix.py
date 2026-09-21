"""Corrects the drift analysis: wrong-arg calls only count when the FRAMEWORK's
schema expects `content` (strands drift) but the model sends `text`.

Schema reality per framework/scenario (from traces):
  strands base/tight : tool param = `text`  -> text args are CORRECT
  strands drift      : tool param = `content` -> text args are WRONG (model trusted prompt)
  crewai all         : tool param = `text` (wrapper keeps old name) -> text args CORRECT
  langgraph all      : no tool schema (code-invoked tools) -> nothing to mis-arg
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
from parse_sse import parse_sse  # noqa: E402

TRACE_DIR = ROOT / "traces"


def get_parsed(rec):
    resp = rec["response"]
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
            "reasoning": msg.get("reasoning") or "",
            "finish_reason": resp["choices"][0].get("finish_reason"),
            "usage": resp.get("usage"),
        }
    return {"content": "", "tool_calls": [], "reasoning": ""}


def analyze_run(path):
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    run = {"n_llm_calls": len(recs), "tokens": 0, "latency_s": 0.0,
           "verify_calls": 0, "wc_results": [], "wrong_arg_calls": 0,
           "final_words": None, "reasoning_chars": 0}
    last_content = ""
    for r in recs:
        p = get_parsed(r)
        run["latency_s"] += r["elapsed_s"]
        u = p.get("usage") or {}
        run["tokens"] += u.get("total_tokens", 0) or 0
        run["reasoning_chars"] += len(p.get("reasoning") or "")
        # what param name does the framework's schema expect for word-count tools?
        schema_param = None
        for t in r["request"].get("tools", []):
            if "word_count" in t["function"]["name"] or "count" in t["function"]["name"]:
                props = (t["function"].get("parameters") or {}).get("properties", {})
                if props:
                    schema_param = list(props.keys())[0]
        for tc in p.get("tool_calls", []):
            name = tc.get("name", "")
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                run["wrong_arg_calls"] += 1
                args = {}
            if "count" in name or "word_count" in name:
                run["verify_calls"] += 1
                if schema_param:
                    # drift test: model must follow the SCHEMA, not the prompt's old name
                    if schema_param not in args:
                        run["wrong_arg_calls"] += 1
                if "content" in args:
                    last_content = args["content"]
        for m in r["request"].get("messages", []):
            if m.get("role") == "tool":
                try:
                    d = json.loads(m.get("content") or "{}")
                    if isinstance(d, dict) and "word_count" in d:
                        run["wc_results"].append(d["word_count"])
                except json.JSONDecodeError:
                    pass
        content = (p.get("content") or "").strip()
        if content and len(content) > 80 and p.get("finish_reason") == "stop":
            last_content = content
    run["final_words"] = len([w for w in last_content.split() if w.strip()]) if last_content else None
    return run


def main():
    files = sorted(TRACE_DIR.glob("llm_calls_*__*.jsonl"))
    all_runs = []
    for f in files:
        stem = f.stem.replace("llm_calls_", "")
        fw, rest = stem.split("__", 1)
        run = analyze_run(f)
        run["file"] = f.name
        run["framework"] = fw
        run["label"] = rest
        all_runs.append(run)

    agg = {}
    for r in all_runs:
        scenario = r["label"].split("_run")[0]
        agg.setdefault((r["framework"], scenario), []).append(r)

    print("=" * 72)
    print("NONDETERMINISM & RESILIENCE REPORT v2 (schema-aware drift detection)")
    print("model: (see trace metadata for the exact model), 3 runs per cell, 27 runs total")
    print("=" * 72)
    for key in sorted(agg):
        fw, scenario = key
        runs = agg[key]
        n = len(runs)
        verified = sum(1 for r in runs if r["verify_calls"] > 0)
        wrong_args = sum(r["wrong_arg_calls"] for r in runs)
        tokens = [r["tokens"] for r in runs]
        lat = [r["latency_s"] for r in runs]
        calls = [r["n_llm_calls"] for r in runs]
        words = [r["final_words"] for r in runs if r["final_words"]]
        print(f"\n--- {fw} / {scenario} ({n} runs)")
        print(f"  verify-tool used: {verified}/{n} runs")
        print(f"  schema-drift failures (model sent old arg name): {wrong_args}")
        print(f"  LLM calls: {calls}")
        print(f"  tokens mean: {round(sum(tokens)/n)} (spread {min(tokens)}-{max(tokens)})")
        print(f"  latency mean: {round(sum(lat)/n,1)}s")
        if words:
            print(f"  final words: {words} (spread {max(words)-min(words)})")
        wc_all = [w for r in runs for w in r["wc_results"]]
        if wc_all:
            print(f"  wc tool results observed: {wc_all}")

    out = {
        "runs": all_runs,
        "aggregates": {
            f"{fw}/{sc}": {
                "n": len(runs),
                "verify_rate": sum(1 for r in runs if r["verify_calls"] > 0) / len(runs),
                "schema_drift_failures": sum(r["wrong_arg_calls"] for r in runs),
                "tokens_mean": round(sum(r["tokens"] for r in runs) / len(runs)),
                "latency_mean_s": round(sum(r["latency_s"] for r in runs) / len(runs), 1),
                "llm_calls": [r["n_llm_calls"] for r in runs],
                "final_words": [r["final_words"] for r in runs],
            }
            for (fw, sc), runs in sorted(agg.items())
        },
    }
    (ROOT / "artifacts" / "matrix_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nsaved -> artifacts/matrix_report.json")


if __name__ == "__main__":
    main()
