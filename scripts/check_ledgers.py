#!/usr/bin/env python3
"""Keep the article ledgers honest against the regenerated reports.

Each ledger quotes numbers that were measured from the committed traces. This
gate re-derives those numbers from the reports the analyzers just wrote and
refuses the run if a ledger quotes something else — the failure mode it exists
for is a ledger that keeps a figure after the evidence moved.

Run after the analyzers:

    python3 runs/analyze_llm_counting.py
    python3 runs/analyze_source_boundary.py
    python3 scripts/check_ledgers.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

COUNTING_LEDGER = ROOT / "articles" / "tool-counts-vs-model-counts" / "README.md"
PROVENANCE_LEDGER = ROOT / "articles" / "detail-provenance-boundary" / "README.md"


def main() -> int:
    failures = 0

    counting = json.loads((ART / "llm_counting_report.json").read_text())["aggregates"]
    # thousands separators are a formatting choice in the prose, not a different
    # number, so the comparison normalises them away
    ledger = COUNTING_LEDGER.read_text().replace(",", "")
    name = COUNTING_LEDGER.name

    # the six size-330 cells, as the ledger's result table states them
    for framework in ("crewai", "langgraph", "strands"):
        for cell in ("ids", "stats"):
            row = counting[f"{framework}/{cell}/s330"]
            pct = 100 * row["correct"] / row["n"]
            if not any(form in ledger for form in (f"{pct:.1f}%", f"{pct:.0f}%")):
                print(f"FAIL: {name}: {framework}/{cell}/s330 count% {pct:.1f}% not quoted")
                failures += 1
            if str(row["tokens_mean_scored"]) not in ledger:
                print(f"FAIL: {name}: {framework}/{cell}/s330 tokens {row['tokens_mean_scored']} not quoted")
                failures += 1

    provenance = json.loads((ART / "source_boundary_report.json").read_text())["aggregates"]
    ledger = PROVENANCE_LEDGER.read_text()
    name = PROVENANCE_LEDGER.name

    # the malicious row of each framework: planted detail must always win and the
    # service-owned value must never survive
    for key, row in sorted(provenance.items()):
        if "malicious" not in key:
            continue
        framework = key.split("/")[0]
        if row["leaked"] != row["n"] or row["retained"] != 0:
            print(f"FAIL: {key}: the ledger claims the planted detail always wins; "
                  f"evidence says leaked={row['leaked']}/{row['n']} retained={row['retained']}")
            failures += 1
            continue
        marker = f"| {framework} | malicious | **{row['leaked']}/{row['n']}** | **{row['retained']}/{row['n']}** |"
        if marker not in ledger:
            print(f"FAIL: {name}: missing or stale malicious row for {framework}: {marker!r}")
            failures += 1

    if failures:
        print(f"\nledger check: {failures} mismatch(es)")
        return 1
    print("ledger check: every quoted figure matches the regenerated reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
