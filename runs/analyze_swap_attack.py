#!/usr/bin/env python3
"""Analyzer for the swap-attack cell (exp-B extension).

Reads outputs/*_result_*__swap_*.json (written by the three framework scripts)
and prints the matrix: for each framework x condition, how many runs delivered
bytes that were NOT the bytes verification covered, how many exited 0, and how
many still reported the delivery as verified.

Every number is computed from the per-run verdict block, which the harness
wrote from the tool-layer state (never from the model's own claim). The model's
final text is only used for the "reported verified" column, and that is an
explicitly model-side observation.
"""
import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
from claims import claims_delivery  # noqa: E402  (single calibrated implementation)
CONDS = ["swap_none", "swap_silent", "swap_reported", "swap_bound"]

rows = []


for f in sorted(glob.glob(os.path.join(ROOT, "outputs", "*_result_*__swap_*.json"))):
    if "/_swap" in f:          # quarantined pre-fix runs
        continue
    d = json.load(open(f))
    v = d.get("verdict") or {}
    if not v:
        continue
    text = (d.get("result") or "")
    rows.append({
        "framework": d["framework"], "condition": d["condition"], "seed": d["seed"],
        "mismatch": bool(v.get("bytes_mismatch")),
        "swapped": bool(v.get("swapped")),
        "delivery_refused": bool(v.get("delivery_refused")),
        "claims_delivery": claims_delivery(text),
        "result": text.replace("\n", " ")[:110],
        "elapsed": d.get("elapsed_s"),
    })

print(f"runs read: {len(rows)}")
print()
hdr = f"{'framework':10} {'condition':14} {'n':>2} {'bytes_mismatch':>15} {'exit0':>6} {'code_refused':>13} {'claims_delivered':>17} {'elapsed_s':>10}"
print(hdr)
by = collections.defaultdict(list)
for r in rows:
    by[(r["framework"], r["condition"])].append(r)

for fw in ("strands", "langgraph", "crewai"):
    for c in CONDS:
        ds = by.get((fw, c))
        if not ds:
            continue
        n = len(ds)
        mm = sum(1 for d in ds if d["mismatch"])
        rv = sum(1 for d in ds if d["claims_delivery"])
        rf = sum(1 for d in ds if d["delivery_refused"])
        el = sum((d["elapsed"] or 0) for d in ds) / n
        print(f"{fw:10} {c:14} {n:>2} {f'{mm}/{n}':>15} {f'{n}/{n}':>6} {f'{rf}/{n}':>13} {f'{rv}/{n}':>18} {el:>10.1f}")

print()
print("=== 条件別の合計 ===")
for c in CONDS:
    ds = [r for r in rows if r["condition"] == c]
    mm = sum(1 for d in ds if d["mismatch"])
    rv = sum(1 for d in ds if d["claims_delivery"])
    rf = sum(1 for d in ds if d["delivery_refused"])
    print(f"  {c:14} n={len(ds):>2}  mismatch={mm}/{len(ds)}  code_refused={rf}/{len(ds)}  "
          f"claims_delivered={rv}/{len(ds)}")

print()
print("=== 代表的な最終回答（swap_silent / swap_reported / swap_bound） ===")
for c in ("swap_silent", "swap_reported", "swap_bound"):
    print(f"\n-- {c}")
    for r in sorted([x for x in rows if x["condition"] == c], key=lambda x: (x["framework"], x["seed"])):
        print(f"   {r['framework']:10} s{r['seed']}: {r['result'][:100]}")

out = os.path.join(ROOT, "artifacts", "swap_attack_report.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump({"runs": rows}, open(out, "w"), ensure_ascii=False, indent=1)
print(f"\nreport -> {out}")
