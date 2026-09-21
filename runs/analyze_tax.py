"""Framework Tax analysis: what each framework ADDS to the first LLM call.

Measures, from the recorded proxy traces (27 runs, scenario=base):
  - first-call request composition: system chars, user chars, tool schema chars
  - billed prompt tokens (API ground truth) + cached/fresh split
  - the "framework tax": everything in the first call MINUS the common task text
    (the digest instruction + 5 headlines, identical across all three) and
    MINUS the minimal tool schema needed for the task

The common task text = langgraph's user message (the purest form, no framework
wrapping). The minimal tool surface = the 2 tools in OpenAI function format with
short descriptions (what a no-framework agent would send).

Output: artifacts/framework_tax.json + stdout table.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "common"))

from parse_sse import parse_sse  # noqa: E402
from tools import HEADLINES      # noqa: E402


def load(fw, scenario, run):
    path = ROOT / "traces" / f"llm_calls_{fw}__{fw}__{scenario}_run{run}.jsonl"
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


def text_of(m):
    c = m.get("content")
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(
            p.get("text") or json.dumps(p) if isinstance(p, dict) else str(p) for p in c
        )
    return str(c)


# --- Common task text (identical across frameworks by design) ---
hl = HEADLINES["AI agents"][:5]
TASK_TEXT = (
    "Write a tech news digest of about 100 words based on these headlines.\n"
    "Output the digest text only.\n\nHeadlines:\n" + "\n".join(f"- {h}" for h in hl)
)

# --- Minimal tool surface: 2 tools, short descriptions (no-framework baseline) ---
MIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_headlines",
            "description": "Fetch 5 tech headlines about AI agents.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "count": {"type": "integer"}},
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_word_count",
            "description": "Count words in a text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
]
MIN_SYS = "You are a tech news digest writer. Call the tools as needed, then output the final digest text only."


def char_len(s):
    return len(s)


def main():
    rows = {}
    for fw in ["strands", "langgraph", "crewai"]:
        runs_data = []
        for run in [1, 2, 3]:
            n = norm(load(fw, "base", run))
            first = n[0]
            req = first["req"]
            msgs = req["messages"]
            sysc = "\n".join(text_of(m) for m in msgs if m.get("role") == "system")
            userc = "\n".join(text_of(m) for m in msgs if m.get("role") == "user")
            tools = req.get("tools") or []
            tj = json.dumps(tools)
            u = first["usage"] or {}
            pt = u.get("prompt_tokens", 0)
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            # framework tax = first-call content MINUS common task text MINUS minimal tools
            tax_chars = char_len(sysc) + char_len(userc) + len(tj) - len(TASK_TEXT) - len(json.dumps(MIN_TOOLS))
            # minimal baseline also includes a 1-line system prompt
            tax_chars -= char_len(MIN_SYS)
            runs_data.append({
                "run": run,
                "sys_chars": char_len(sysc),
                "user_chars": char_len(userc),
                "tools_chars": len(tj),
                "n_tools": len(tools),
                "prompt_tokens": pt,
                "cached_tokens": cached,
                "fresh_tokens": pt - cached,
                "tax_chars": tax_chars,
                "calls_in_run": len(lines := n),
            })
        # identical across runs? verify
        identical = all(
            (r["sys_chars"], r["user_chars"], r["tools_chars"], r["prompt_tokens"])
            == (runs_data[0]["sys_chars"], runs_data[0]["user_chars"], runs_data[0]["tools_chars"], runs_data[0]["prompt_tokens"])
            for r in runs_data
        )
        rows[fw] = {
            "runs": runs_data,
            "identical_across_runs": identical,
            "first_call": runs_data[0],
        }

    # Per-run billed totals (whole run, not just first call)
    totals = {}
    for fw in ["strands", "langgraph", "crewai"]:
        run_tot = []
        for run in [1, 2, 3]:
            n = norm(load(fw, "base", run))
            pt = sum((x["usage"] or {}).get("prompt_tokens", 0) for x in n)
            ct = sum((x["usage"] or {}).get("completion_tokens", 0) for x in n)
            lat = sum(x["elapsed"] or 0 for x in n)
            run_tot.append({"run": run, "prompt_tokens": pt, "completion_tokens": ct,
                            "elapsed_s": round(lat, 2), "calls": len(n)})
        totals[fw] = run_tot

    report = {
        "method": {
            "common_task_text": TASK_TEXT,
            "task_text_chars": len(TASK_TEXT),
            "min_tool_surface": MIN_TOOLS,
            "min_tool_chars": len(json.dumps(MIN_TOOLS)),
            "min_system_prompt": MIN_SYS,
            "note": ("framework tax = (first-call sys + user + tool schema chars) "
                     "- task_text_chars - min_tool_chars - min_system_chars. "
                     "The common task text is identical across frameworks by design; "
                     "langgraph's user message IS the task text (verified)."),
        },
        "first_call": rows,
        "run_totals_base": totals,
    }

    out = ROOT / "artifacts" / "framework_tax.json"
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"saved: {out}\n")
    print(f"common task text: {len(TASK_TEXT)} chars | minimal tools: {len(json.dumps(MIN_TOOLS))} chars | minimal system: {len(MIN_SYS)} chars")
    print(f"BASELINE (no framework): {len(MIN_SYS) + len(TASK_TEXT) + len(json.dumps(MIN_TOOLS))} chars of request content")
    print()
    print(f"{'framework':10s} {'sys':>6s} {'user':>6s} {'tools':>6s} {'first-call total':>17s} {'tax vs baseline':>16s} {'prompt_tok':>10s} {'fresh':>6s} identical")
    baseline_total = len(MIN_SYS) + len(TASK_TEXT) + len(json.dumps(MIN_TOOLS))
    for fw, d in rows.items():
        fc = d["first_call"]
        total_fc = fc["sys_chars"] + fc["user_chars"] + fc["tools_chars"]
        print(f"{fw:10s} {fc['sys_chars']:6d} {fc['user_chars']:6d} {fc['tools_chars']:6d} {total_fc:17d} {total_fc - baseline_total:+16d} {fc['prompt_tokens']:10d} {fc['fresh_tokens']:6d} {d['identical_across_runs']}")

    print("\nrun totals (base scenario):")
    for fw, rt in totals.items():
        for r in rt:
            print(f"  {fw:10s} run{r['run']}: prompt={r['prompt_tokens']:5d} completion={r['completion_tokens']:4d} calls={r['calls']} latency={r['elapsed_s']}s")


if __name__ == "__main__":
    main()
