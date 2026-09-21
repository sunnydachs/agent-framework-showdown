"""B-scaling analysis: task shape x framework - the scaling curve.

Combines:
  - the 27-run base matrix (linear digest task, 1 tool call + verify)
  - the 9-run complex matrix (topic comparison: 2 fetches + branch + digest + verify)

For each (task, framework): calls, prompt tokens, completion tokens, latency,
word-count spread across 3 runs. Plus the first-call composition (framework tax)
per task shape, from the recorded proxy traces.

Known data caveat: strands complex run2 returned an empty content field
(finish_reason=stop, full digest in reasoning) - the digest word count is
recovered from the check_word_count tool argument (106 words). This is an
honest failure mode of the model-driven design and is reported as such.

Output: artifacts/scaling_report.json + stdout tables.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "common"))

from parse_sse import parse_sse  # noqa: E402

# Empty-content final calls (finish_reason=stop, full digest only in reasoning /
# in the last tool argument): the digest word count is recovered from the
# check_word_count tool argument. Verified against traces 2026-09-21:
#   strands base run2  -> output_wc=0 (empty), tool-arg wc=100
#   strands complex run2 -> output_wc=0 (empty), tool-arg wc=106
# This is an honest failure mode of the model-driven design (model "finishes"
# without emitting visible content) and is reported as such.
WC_OVERRIDE = {("strands", "base", 2): 100, ("strands", "complex", 2): 106}


def load(fw, task, run):
    path = ROOT / "traces" / f"llm_calls_{fw}__{fw}__{task if task == 'complex' else fw + '__' + task}_run{run}.jsonl"
    # base matrix labels are "<fw>__<scenario>_run<N>" with an extra fw segment:
    # llm_calls_<fw>__<fw>__<scenario>_run<N>.jsonl
    if task != "complex":
        path = ROOT / "traces" / f"llm_calls_{fw}__{fw}__{task}_run{run}.jsonl"
    else:
        path = ROOT / "traces" / f"llm_calls_{fw}__{fw}__complex_run{run}.jsonl"
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


def word_counts(fw, task):
    out = []
    for run in [1, 2, 3]:
        if (fw, task, run) in WC_OVERRIDE:
            out.append(WC_OVERRIDE[(fw, task, run)])
            continue
        p = ROOT / "outputs"
        if task == "complex":
            f = p / f"{fw}_complex_{fw}__complex_run{run}.json"
        else:
            f = p / f"{fw}_result_{fw}__{task}_run{run}.json"
        if not f.exists():
            out.append(None)
            continue
        d = json.load(open(f))
        wc = d.get("word_count")
        if wc is None:
            wc = len([w for w in str(d.get("result", "")).split() if w.strip()])
        out.append(wc)
    return out


def spread(vals):
    v = [x for x in vals if x is not None]
    return (max(v) - min(v)) if v else None


def analyze_cell(fw, task):
    calls_list, pts, cts, lats, first_pts = [], [], [], [], []
    for run in [1, 2, 3]:
        n = norm(load(fw, task, run))
        calls_list.append(len(n))
        pts.append(sum((x["usage"] or {}).get("prompt_tokens", 0) for x in n))
        cts.append(sum((x["usage"] or {}).get("completion_tokens", 0) for x in n))
        lats.append(round(sum(x["elapsed"] or 0 for x in n), 2))
        first_pts.append((n[0]["usage"] or {}).get("prompt_tokens", 0))
    first = norm(load(fw, task, 1))[0]
    msgs = first["req"]["messages"]
    sysc = "\n".join(text_of(m) for m in msgs if m.get("role") == "system")
    userc = "\n".join(text_of(m) for m in msgs if m.get("role") == "user")
    tools = json.dumps(first["req"].get("tools") or [])
    wcs = word_counts(fw, task)
    return {
        "calls": calls_list,
        "prompt_tokens": pts,
        "completion_tokens": cts,
        "latency_s": lats,
        "first_call_prompt_tokens": first_pts,
        "first_call_chars": {"sys": len(sysc), "user": len(userc), "tools": len(tools)},
        "word_counts": wcs,
        "wc_spread": spread(wcs),
        "avg_calls": round(sum(calls_list) / 3, 2),
        "avg_prompt_tokens": round(sum(pts) / 3),
        "avg_completion_tokens": round(sum(cts) / 3),
        "avg_latency_s": round(sum(lats) / 3, 2),
    }


def main():
    report = {}
    for task in ["base", "complex"]:
        for fw in ["strands", "langgraph", "crewai"]:
            report[f"{task}:{fw}"] = analyze_cell(fw, task)

    # Scaling multipliers: complex vs base per framework
    mult = {}
    for fw in ["strands", "langgraph", "crewai"]:
        b, c = report[f"base:{fw}"], report[f"complex:{fw}"]
        mult[fw] = {
            "calls": round(c["avg_calls"] / b["avg_calls"], 2),
            "prompt_tokens": round(c["avg_prompt_tokens"] / b["avg_prompt_tokens"], 2),
            "completion_tokens": round(c["avg_completion_tokens"] / b["avg_completion_tokens"], 2),
            "latency": round(c["avg_latency_s"] / b["avg_latency_s"], 2),
        }

    out = ROOT / "artifacts" / "scaling_report.json"
    with open(out, "w") as f:
        json.dump({"cells": report, "scaling_multipliers": mult,
                   "caveat": "strands complex run2: empty content (finish_reason=stop, digest in reasoning); wc recovered from tool arg (106)."},
                  f, ensure_ascii=False, indent=1)

    print(f"saved: {out}\n")
    hdr = f"{'cell':16s} {'calls':>7s} {'prompt':>7s} {'compl':>7s} {'lat_s':>7s} {'wc spread':>9s} {'1st call':>9s}"
    print(hdr)
    print("-" * len(hdr))
    for key in ["base:strands", "base:langgraph", "base:crewai", "complex:strands", "complex:langgraph", "complex:crewai"]:
        d = report[key]
        print(f"{key:16s} {str(d['calls']):>7s} {d['avg_prompt_tokens']:7d} {d['avg_completion_tokens']:7d} {d['avg_latency_s']:7.2f} {str(d['wc_spread']):>9s} {d['first_call_prompt_tokens'][0]:9d}")

    print("\nscaling multipliers (complex / base):")
    for fw, m in mult.items():
        print(f"  {fw:10s}: calls x{m['calls']}  prompt x{m['prompt_tokens']}  completion x{m['completion_tokens']}  latency x{m['latency']}")

    print("\nfirst-call composition (chars, complex task):")
    for fw in ["strands", "langgraph", "crewai"]:
        fc = report[f"complex:{fw}"]["first_call_chars"]
        print(f"  {fw:10s}: sys={fc['sys']} user={fc['user']} tools={fc['tools']}")


if __name__ == "__main__":
    main()
