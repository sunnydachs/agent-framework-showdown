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
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

COUNTING_LEDGER = ROOT / "articles" / "tool-counts-vs-model-counts" / "README.md"
COUNTING_EVIDENCE = ROOT / "articles" / "tool-counts-vs-model-counts" / "evidence.md"
PROVENANCE_LEDGER = ROOT / "articles" / "detail-provenance-boundary" / "README.md"

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def table_rows(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        yield [c.strip() for c in line.strip("|").split("|")]


def check_wrong_answers(report: dict, readme: str, evidence: str) -> list[str]:
    """The wrong-answer table and the sentence that counts how many of them never
    called the tool. The table was right while the sentence still said 'two' of
    three, so the sentence is checked against the report like any other figure."""
    out: list[str] = []
    by_label = {r["label"]: r for r in report["runs"]}
    seen = 0
    for cells in table_rows(evidence):
        label = cells[0].strip("`")
        if label not in by_label or len(cells) < 5:
            continue
        run = by_label[label]
        seen += 1
        answered, true, calls = cells[2], cells[3], cells[4]
        if run.get("count_correct") is not False:
            out.append(f"evidence lists {label} as a wrong answer; the report scores it "
                       f"count_correct={run.get('count_correct')}")
        elif (str(run["answer"]), str(run["true_count"]), str(run["n_tool_calls"])) != (answered, true, calls):
            out.append(f"evidence row {label}: ledger says answered={answered} true={true} "
                       f"tool_calls={calls}; report says answered={run['answer']} "
                       f"true={run['true_count']} tool_calls={run['n_tool_calls']}")

    wrong = [r for r in report["runs"] if r.get("outcome") == "wrong_count"]
    if seen != len(wrong):
        out.append(f"wrong-answer table has {seen} rows; the report has {len(wrong)} wrong runs")

    silent = [r for r in wrong if r["n_tool_calls"] == 0]
    m = re.search(r"\b(one|two|three|four|five|\d+)\b of those runs answered[^.]*without calling the tool",
                  readme, re.I)
    if not m:
        out.append("the README no longer states how many wrong answers never called the tool")
    else:
        word = m.group(1).lower()
        claimed = NUMBER_WORDS.get(word) if not word.isdigit() else int(word)
        if claimed != len(silent):
            out.append(f"the README says {word} wrong answers never called the tool; "
                       f"the report has {len(silent)}")
    return out


def main() -> int:
    failures = 0

    counting = json.loads((ART / "llm_counting_report.json").read_text())
    aggregates = counting["aggregates"]
    # thousands separators are a formatting choice in the prose, not a different
    # number, so the comparison normalises them away
    ledger = COUNTING_LEDGER.read_text().replace(",", "")
    name = COUNTING_LEDGER.name

    # the six size-330 cells, as the ledger's result table states them
    for framework in ("crewai", "langgraph", "strands"):
        for cell in ("ids", "stats"):
            row = aggregates[f"{framework}/{cell}/s330"]
            pct = 100 * row["correct"] / row["n"]
            if not any(form in ledger for form in (f"{pct:.1f}%", f"{pct:.0f}%")):
                print(f"FAIL: {name}: {framework}/{cell}/s330 count% {pct:.1f}% not quoted")
                failures += 1
            if str(row["tokens_mean_scored"]) not in ledger:
                print(f"FAIL: {name}: {framework}/{cell}/s330 tokens {row['tokens_mean_scored']} not quoted")
                failures += 1

    for problem in check_wrong_answers(counting, COUNTING_LEDGER.read_text(), COUNTING_EVIDENCE.read_text()):
        print(f"FAIL: {name}: {problem}")
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
