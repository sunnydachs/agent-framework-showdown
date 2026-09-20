"""Aggregates all three framework traces into one comparison report.

Reads traces/llm_calls_<framework>.jsonl, parses streaming/non-streaming
responses uniformly, and prints a framework-by-framework behavioral report:
LLM call count, message growth pattern, tool calls, token totals, latency,
and the observed execution flow.

Run: python proxy/report.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
from parse_sse import parse_sse  # noqa: E402


def get_parsed(rec):
    resp = rec["response"]
    if "_raw" in resp:
        return parse_sse(resp["_raw"])
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


def analyze(framework):
    path = ROOT / "traces" / f"llm_calls_{framework}.jsonl"
    if not path.exists():
        return None
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    calls = []
    total_tokens = 0
    total_reasoning_chars = 0
    for r in recs:
        p = get_parsed(r)
        u = p.get("usage") or {}
        total_tokens += u.get("total_tokens", 0) or 0
        total_reasoning_chars += len(p.get("reasoning") or "")
        calls.append(
            {
                "msgs_in": len(r["request"].get("messages", [])),
                "elapsed_s": r["elapsed_s"],
                "tools_called": [t["name"] for t in p.get("tool_calls", [])],
                "finish": p.get("finish_reason"),
                "tokens": u.get("total_tokens"),
                "has_reasoning": bool(p.get("reasoning")),
                "content_len": len((p.get("content") or "").strip()),
            }
        )
    total_latency = sum(c["elapsed_s"] for c in calls)
    return {
        "framework": framework,
        "n_llm_calls": len(calls),
        "total_tokens": total_tokens,
        "total_latency_s": round(total_latency, 1),
        "total_reasoning_chars": total_reasoning_chars,
        "calls": calls,
    }


def main():
    report = {}
    for fw in ["strands", "langgraph", "crewai"]:
        a = analyze(fw)
        if a:
            report[fw] = a
            print(f"=== {fw.upper()} ===")
            print(f"  LLM calls: {a['n_llm_calls']}")
            print(f"  total tokens: {a['total_tokens']}")
            print(f"  total LLM latency: {a['total_latency_s']}s")
            print(f"  reasoning chars (thinking out loud): {a['total_reasoning_chars']}")
            for i, c in enumerate(a["calls"]):
                print(
                    f"  call {i+1}: msgs_in={c['msgs_in']}, tools={c['tools_called'] or '-'}, "
                    f"finish={c['finish']}, tokens={c['tokens']}, {c['elapsed_s']}s"
                )
            print()
    (ROOT / "artifacts" / "comparison_report.json").parent.mkdir(exist_ok=True)
    (ROOT / "artifacts" / "comparison_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1)
    )
    print("saved -> artifacts/comparison_report.json")


if __name__ == "__main__":
    main()
