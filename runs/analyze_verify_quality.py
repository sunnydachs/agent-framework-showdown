#!/usr/bin/env python3
"""Analyzer for the verifier-quality cell (exp-B follow-up).

Reads outputs/*_result_*__verify_quality_*.json and reports, per cell and per
framework, what the delivery path actually did: whether the artifact was bound
to its receipt (it is, in every cell), whether the artifact violated the
declared predicate (it does, in every cell), whether the receipt claimed a
check, whether a check demonstrably ran, and which guard — if any — stopped the
delivery.

Every column comes from the harness's recorded state. The model's own final
text is used for exactly one column, `claims_verified`, and that column is
labelled as model-side in the report.

Asserts (these are the point — a table whose rows do not partition the runs is
not evidence):
  * every run's guards sum to n (each run fired exactly one guard bucket)
  * delivered + refused == n
  * delivered_wrong <= delivered
  * a run that shipped bytes that violate the predicate is counted as
    delivered_wrong, never silently dropped
"""
import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
from claims import claims_delivery  # noqa: E402
from verify_quality import CELL_ORDER  # noqa: E402

OUT = os.path.join(ROOT, "artifacts", "verify_quality_report.json")
MANIFEST = os.path.join(ROOT, "runs", "manifest_verify_quality.jsonl")
MANIFEST_BRIDGE = os.path.join(ROOT, "runs", "manifest_verify_quality_bridge.jsonl")
FRAMEWORKS = ["strands", "langgraph", "crewai"]

rows = []
man = {}
for path in (MANIFEST, MANIFEST_BRIDGE):
    if os.path.exists(path):
        for line in open(path):
            if line.strip():
                rec = json.loads(line)
                man[rec["label"]] = rec

for f in sorted(glob.glob(os.path.join(ROOT, "outputs", "*_result_*__verify_quality_*.json"))):
    if "/_" in f:                     # quarantined pre-fix / smoke runs
        continue
    d = json.load(open(f))
    v = d.get("verdict") or {}
    if not v or v.get("cell") not in CELL_ORDER:
        continue
    m = man.get(d.get("run_label", ""), {})
    rows.append({
        "label": d.get("run_label", ""),
        "framework": d.get("framework", ""),
        "cell": v["cell"],
        "family": v.get("family", ""),
        "seed": v.get("seed", 0),
        "elapsed_s": d.get("elapsed_s"),
        # model/provider come from the runner's manifest, which recorded them
        # from what the proxy actually served, not from a file on disk
        "model": m.get("model", ""),
        "provider": m.get("provider", ""),
        "bytes_bound": bool(v.get("bytes_bound")),
        "artifact_violates_predicate": bool(v.get("artifact_violates_predicate")),
        "receipt_names_check": bool(v.get("receipt_names_check")),
        "receipt_carries_witness": bool(v.get("receipt_carries_witness")),
        "witness_empty_while_violating": bool(v.get("witness_empty_while_violating")),
        "verifier_executed": bool(v.get("verifier_executed")),
        "control_ran": bool(v.get("control_ran")),
        "control_verified_bad_artifact": bool(v.get("control_verified_bad_artifact")),
        "delivered": bool(v.get("delivered")),
        "delivered_wrong": bool(v.get("delivered_wrong")),
        "delivery_status": v.get("delivery_status", ""),
        "guard_fired": v.get("guard_fired", "none"),
        # model-side column, computed here from the final answer
        "claims_verified": claims_delivery(d.get("result") or ""),
    })

agg = collections.OrderedDict()
for r in rows:
    key = f"{r['framework']}/{r['cell']}"
    a = agg.setdefault(key, {"n": 0, "bytes_bound": 0, "artifact_violates": 0,
                             "receipt_names_check": 0, "receipt_carries_witness": 0,
                             "witness_empty_while_violating": 0, "verifier_executed": 0,
                             "control_ran": 0, "control_verified_bad": 0,
                             "delivered": 0, "delivered_wrong": 0, "refused": 0,
                             "claims_verified": 0, "guards": collections.Counter()})
    a["n"] += 1
    for k, src in (("bytes_bound", "bytes_bound"),
                   ("artifact_violates", "artifact_violates_predicate"),
                   ("receipt_names_check", "receipt_names_check"),
                   ("receipt_carries_witness", "receipt_carries_witness"),
                   ("witness_empty_while_violating", "witness_empty_while_violating"),
                   ("verifier_executed", "verifier_executed"),
                   ("control_ran", "control_ran"),
                   ("control_verified_bad", "control_verified_bad_artifact"),
                   ("delivered", "delivered"), ("delivered_wrong", "delivered_wrong"),
                   ("claims_verified", "claims_verified")):
        a[k] += 1 if r[src] else 0
    a["refused"] += 0 if r["delivered"] else 1
    a["guards"][r["guard_fired"]] += 1

# cross-framework view per cell (the numbers the ledger quotes)
cells = collections.OrderedDict()
for c in CELL_ORDER:
    ds = [r for r in rows if r["cell"] == c]
    cells[c] = {
        "n": len(ds),
        "frameworks": sorted({r["framework"] for r in ds}),
        "bytes_bound": sum(1 for r in ds if r["bytes_bound"]),
        "artifact_violates": sum(1 for r in ds if r["artifact_violates_predicate"]),
        "verifier_executed": sum(1 for r in ds if r["verifier_executed"]),
        "control_ran": sum(1 for r in ds if r["control_ran"]),
        "control_verified_bad": sum(1 for r in ds if r["control_verified_bad_artifact"]),
        "delivered": sum(1 for r in ds if r["delivered"]),
        "delivered_wrong": sum(1 for r in ds if r["delivered_wrong"]),
        "claims_verified": sum(1 for r in ds if r["claims_verified"]),
        "guards": dict(collections.Counter(r["guard_fired"] for r in ds)),
    }

# --- asserts ---------------------------------------------------------------
problems = []
for key, a in agg.items():
    if sum(a["guards"].values()) != a["n"]:
        problems.append(f"{key}: guard buckets {dict(a['guards'])} do not sum to n={a['n']}")
    if a["delivered"] + a["refused"] != a["n"]:
        problems.append(f"{key}: delivered+refused != n")
    if a["delivered_wrong"] > a["delivered"]:
        problems.append(f"{key}: delivered_wrong > delivered")
    if a["delivered_wrong"] and not a["artifact_violates"]:
        problems.append(f"{key}: shipped a wrong artifact with no recorded violation")
for c, a in cells.items():
    if a["n"] and set(a["frameworks"]) != set(FRAMEWORKS):
        problems.append(f"{c}: frameworks present = {a['frameworks']}, expected {FRAMEWORKS}")

manifest_ok = 0
manifest_n = 0
for path in (MANIFEST, MANIFEST_BRIDGE):
    if os.path.exists(path):
        recs = [json.loads(l) for l in open(path) if l.strip()]
        manifest_n += len(recs)
        manifest_ok += sum(1 for r in recs if r.get("ok"))

# The bridge: one cell of the PREVIOUS grid re-run on the provider this grid
# used. Its purpose is to state whether the platform switch moved the cell, so
# the comparison against the previous report is computed here rather than
# asserted in prose.
bridge_runs = []
for f in sorted(glob.glob(os.path.join(ROOT, "outputs", "*_result_*__verify_quality_bridge_*.json"))):
    if "/_" in f:
        continue
    d = json.load(open(f))
    v = d.get("verdict") or {}
    if "bytes_mismatch" not in v:
        continue
    bridge_runs.append({"label": d.get("run_label", ""),
                        "framework": d.get("framework", ""),
                        "mismatch": bool(v.get("bytes_mismatch")),
                        "refused": bool(v.get("delivery_refused")),
                        "claims_delivery": claims_delivery(d.get("result") or "")})
bridge = {
    "n": len(bridge_runs),
    "mismatch": sum(1 for r in bridge_runs if r["mismatch"]),
    "refused": sum(1 for r in bridge_runs if r["refused"]),
    "claims": sum(1 for r in bridge_runs if r["claims_delivery"]),
    "runs": bridge_runs,
}
prev_path = os.path.join(ROOT, "artifacts", "swap_attack_report.json")
if bridge["n"] and os.path.exists(prev_path):
    prev = [r for r in json.load(open(prev_path))["runs"] if r["condition"] == "swap_silent"]
    bridge["same_as_swap_silent"] = bool(
        prev and bridge["n"] == len(prev)
        and bridge["mismatch"] == sum(1 for r in prev if r["mismatch"])
        and bridge["claims"] == sum(1 for r in prev if r["claims_delivery"]))
else:
    bridge["same_as_swap_silent"] = None

report = {
    "scenario": "verify_quality",
    "note": ("Every column except claims_verified is computed from the harness's "
             "recorded state. claims_verified is model-side: it is the calibrated "
             "sentence-level detector applied to the final answer."),
    "cells_defined": CELL_ORDER,
    "models": sorted({r["model"] for r in rows}),
    "providers": sorted({r["provider"] for r in rows}),
    "runs": rows,
    "aggregates": {k: {**v, "guards": dict(v["guards"])} for k, v in agg.items()},
    "cell_totals": cells,
    "manifest": {"runs": manifest_n, "exited_zero": manifest_ok},
    "bridge": bridge,
    "assert_problems": problems,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, "w"), ensure_ascii=False, indent=1)

print(f"runs: {len(rows)}  |  manifest: {manifest_ok}/{manifest_n} exited 0")
print(f"{'cell':16} {'n':>2} {'bound':>5} {'viol':>4} {'exec':>4} {'ctrl':>4} "
      f"{'ctrl_bad':>8} {'deliv':>5} {'WRONG':>5} {'claims':>6}  guards")
for c, a in cells.items():
    print(f"{c:16} {a['n']:>2} {a['bytes_bound']:>5} {a['artifact_violates']:>4} "
          f"{a['verifier_executed']:>4} {a['control_ran']:>4} {a['control_verified_bad']:>8} "
          f"{a['delivered']:>5} {a['delivered_wrong']:>5} {a['claims_verified']:>6}  {a['guards']}")
if bridge["n"]:
    print(f"\nbridge (swap_silent on this provider): {bridge['n']} runs, "
          f"{bridge['mismatch']}/{bridge['n']} mismatch, "
          f"{bridge['refused']}/{bridge['n']} refused, "
          f"{bridge['claims']}/{bridge['n']} claimed a verified delivery")
    print(f"  previous grid's swap_silent cell is unchanged: "
          f"{bridge['same_as_swap_silent']}")
print("\nasserts:", "PASS" if not problems else "FAIL")
for p in problems:
    print("  -", p)
print(f"report -> {OUT}")
sys.exit(1 if problems else 0)
