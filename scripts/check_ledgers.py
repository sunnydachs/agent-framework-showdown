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
SWAP_LEDGER = ROOT / "articles" / "swap-attack" / "README.md"

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

    # A wrong answer with zero recorded tool calls is the signature of the old
    # name-substring counter (crewai's `fetch_ids` was invisible to it), so treat
    # it as an error in the measurement rather than a behaviour to describe.
    silent = [r for r in wrong if r["n_tool_calls"] == 0]
    if silent:
        out.append(f"{len(silent)} wrong run(s) recorded 0 tool calls "
                   f"({', '.join(r['label'] for r in silent[:3])}) — fix the tool-name matching "
                   f"before quoting that as behaviour")
    return out


def check_contexts(report: dict, readme: str) -> list[str]:
    """The 'what the model actually saw' table. A mode label is not evidence that
    the framework carried the tool's answer through, so the ledger states the
    measured buckets and this re-derives them."""
    out: list[str] = []
    per: dict[tuple[str, str], dict[str, int]] = {}
    for key, a in report["aggregates"].items():
        fw, mode, _ = key.split("/")
        acc = per.setdefault((fw, mode), dict.fromkeys(
            ("count", "ids", "count_and_list", "neither", "no_final_prompt"), 0))
        for bucket, v in a["contexts"].items():
            acc[bucket] = acc.get(bucket, 0) + v
    for (fw, mode), c in sorted(per.items()):
        if c["count_and_list"]:
            out.append(f"{fw} `{mode}`: {c['count_and_list']} run(s) held both the count and the list; "
                       f"the ledger table cannot express that — split the row")
            continue
        n = sum(c.values())
        pat = re.compile(rf"^\|\s*{fw}\s*`{mode}`\s*\|\s*(\d+)\s*\|"          # n
                         r"\s*\**\s*(\d+)\s*\**\s*\|\s*\**\s*(\d+)\s*\**\s*\|"  # count, ids
                         r"\s*(\d+)\s*\|\s*(\d+)\s*\|", re.M)                    # neither, no_prompt
        m = pat.search(readme)
        if not m:
            out.append(f"no contexts row for {fw} `{mode}` in the ledger")
            continue
        got = tuple(int(x) for x in m.groups())
        want = (n, c["count"], c["ids"], c["neither"], c["no_final_prompt"])
        if got != want:
            out.append(f"contexts row {fw} `{mode}`: ledger says {got}, the report says {want}")
    return out


def check_wrong_answer_summary(report: dict, readme: str) -> list[str]:
    """The README's five-row table carries no labels, so match the multiset of
    (answered, true, tool calls) against the report's wrong runs instead. Rows are
    collected under that table's own header — the ledger has other six-column
    tables (the contexts matrix) that would otherwise be read as wrong answers."""
    out: list[str] = []
    want = sorted((r["answer"], r["true_count"], r["n_tool_calls"])
                  for r in report["runs"] if r.get("outcome") == "wrong_count")
    got: list[tuple[int, int, int]] = []
    collecting = False
    for line in readme.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            collecting = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if set(s) <= set("|-: "):
            continue
        joined = " ".join(cells).lower()
        if not collecting:
            collecting = "asked" in joined and "answered" in joined and "true" in joined
            continue
        try:
            got.append((int(cells[2]), int(cells[3]), int(cells[4])))
        except (ValueError, IndexError):
            continue
    if sorted(got) != want:
        out.append(f"wrong-answer summary table: rows say {sorted(got)}, the report says {want}")
    return out


def main() -> int:
    failures = 0

    counting = json.loads((ART / "llm_counting_report.json").read_text())
    aggregates = counting["aggregates"]
    name = COUNTING_LEDGER.name

    # the six size-330 cells, bound to the ledger's own result-table ROW. A flat
    # substring test over the whole file would accept one stray "92.3%" anywhere
    # for every cell, and "14" for the 14,600 token row.
    rows = {c[0].strip().lower(): c for c in table_rows(COUNTING_LEDGER.read_text()) if c}
    for framework in ("crewai", "langgraph", "strands"):
        cells = rows.get(framework)
        if not cells or len(cells) < 5:
            print(f"FAIL: {name}: no result row for {framework}")
            failures += 1
            continue
        for col, cell in ((1, "ids"), (2, "stats")):
            row = aggregates[f"{framework}/{cell}/s330"]
            pct = 100 * row["correct"] / row["n"]
            frac = f"{row['correct']}/{row['n']}"
            if not any(form in cells[col] for form in (f"{pct:.1f}%", f"{pct:.0f}%")) or frac not in cells[col]:
                print(f"FAIL: {name}: {framework}/{cell}/s330 row says {cells[col]!r}; "
                      f"the report says {pct:.1f}% ({frac})")
                failures += 1
        for col, cell in ((3, "ids"), (4, "stats")):
            want = f"{aggregates[f'{framework}/{cell}/s330']['tokens_mean_scored']:,}"
            if want not in cells[col]:
                print(f"FAIL: {name}: {framework}/{cell}/s330 tokens row says {cells[col]!r}; "
                      f"the report says {want}")
                failures += 1

    # the run-count claims: 408 runs, 407 exiting 0, 21-26 per cell
    ledger = COUNTING_LEDGER.read_text()
    if len(counting["runs"]) != 408:
        print(f"FAIL: {name}: the report holds {len(counting['runs'])} runs, the ledger claims 408")
        failures += 1
    ok_runs = sum(1 for r in counting["runs"] if r["process_ok"])
    if ok_runs != 407 or "407 exited 0" not in ledger:
        print(f"FAIL: {name}: {ok_runs} runs exited 0; the ledger says '407 exited 0'")
        failures += 1
    if sorted({a["n"] for a in aggregates.values()}) != [21, 26]:
        print(f"FAIL: {name}: cell sizes are {sorted({a['n'] for a in aggregates.values()})}, the ledger says 21-26")
        failures += 1

    # a report older than the analyzer that produced it is not evidence
    report_path = ART / "llm_counting_report.json"
    if report_path.stat().st_mtime < (ROOT / "runs" / "analyze_llm_counting.py").stat().st_mtime:
        print(f"FAIL: {name}: llm_counting_report.json is older than the analyzer — re-run it")
        failures += 1

    swap_report = ART / "swap_attack_report.json"
    if swap_report.stat().st_mtime < (ROOT / "runs" / "analyze_swap_attack.py").stat().st_mtime:
        print(f"FAIL: {SWAP_LEDGER.name}: swap_attack_report.json is older than the analyzer — re-run it")
        failures += 1

    for problem in check_wrong_answers(counting, COUNTING_LEDGER.read_text(), COUNTING_EVIDENCE.read_text()):
        print(f"FAIL: {name}: {problem}")
        failures += 1

    for problem in check_contexts(counting, COUNTING_LEDGER.read_text()):
        print(f"FAIL: {name}: {problem}")
        failures += 1

    for problem in check_wrong_answer_summary(counting, COUNTING_LEDGER.read_text()):
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

    # --- the ledger's control rows, the ceiling totals, and the swap ledger ---
    ledger_text = PROVENANCE_LEDGER.read_text()

    for key, row in sorted(provenance.items()):
        fw, cond = key.split("/")
        if cond != "clean":
            continue
        marker = f"| {fw} | clean | {row['leaked']}/{row['n']} | {row['retained']}/{row['n']} |"
        if marker not in ledger_text:
            print(f"FAIL: {name}: missing or stale clean row for {fw}: {marker!r}")
            failures += 1

    legit = {k: v for k, v in provenance.items() if k.endswith("/legitimate")}
    cells = {(v["n"], v["leaked"], v["retained"]) for v in legit.values()}
    if len(cells) != 1:
        print(f"FAIL: {name}: the legitimate cells disagree across frameworks: {sorted(cells)}")
        failures += 1
    else:
        n, leaked, retained = cells.pop()
        marker = f"| legitimate | all three | {n} each | {leaked}/{n} | {retained}/{n} |"
        if marker not in ledger_text:
            print(f"FAIL: {name}: missing or stale legitimate row: {marker!r}")
            failures += 1

    # the ceiling cell quotes its own totals, and the same table shape
    ceiling = json.loads((ART / "source_boundary_ceiling_report.json").read_text())["aggregates"]
    for fw in ("crewai", "langgraph", "strands"):
        row = ceiling[f"{fw}/malicious"]
        marker = (f"| malicious | {fw} | {row['n']} | **{row['leaked']}/{row['n']}** | "
                  f"{row['retained']}/{row['n']} |")
        if marker not in ledger_text:
            print(f"FAIL: {name}: missing or stale ceiling row for {fw}: {marker!r}")
            failures += 1
    n_all = sum(v["n"] for v in ceiling.values())
    ok_all = sum(v["process_ok"] for v in ceiling.values())
    mal_leak = sum(v["leaked"] for k, v in ceiling.items() if k.endswith("/malicious"))
    mal_n = sum(v["n"] for k, v in ceiling.items() if k.endswith("/malicious"))
    if f"{n_all} runs, {ok_all} exited 0" not in ledger_text:
        print(f"FAIL: {name}: the ledger does not state '{n_all} runs, {ok_all} exited 0'")
        failures += 1
    if f"{mal_leak} of {mal_n} malicious runs" not in ledger_text:
        print(f"FAIL: {name}: the ledger does not state '{mal_leak} of {mal_n} malicious runs'")
        failures += 1

    # swap-attack ledger: every row of the result table, plus the totals sentence
    swap = json.loads((ART / "swap_attack_report.json").read_text())["runs"]
    swap_ledger = SWAP_LEDGER.read_text()
    for cells in table_rows(swap_ledger):
        if len(cells) != 7:
            continue
        fw, cond = cells[0].replace("**", ""), cells[1].replace("**", "")
        if cond not in ("swap_none", "swap_silent", "swap_reported", "swap_bound"):
            continue
        ds = [r for r in swap if r["condition"] == cond and r["framework"] == fw]
        if not ds:
            print(f"FAIL: {SWAP_LEDGER.name}: the ledger has a {fw}/{cond} row; the report has no runs")
            failures += 1
            continue
        n = len(ds)
        want = {3: f"{sum(1 for r in ds if r['mismatch'])}/{n}",
                5: f"{sum(1 for r in ds if r['delivery_refused'])}/{n}",
                6: f"{sum(1 for r in ds if r['claims_delivery'])}/{n}"}
        for idx, value in want.items():
            if cells[idx].replace("**", "").strip() != value:
                print(f"FAIL: {SWAP_LEDGER.name}: {fw}/{cond} column {idx} says "
                      f"{cells[idx]!r}; the report says {value}")
                failures += 1

    for cond in ("swap_none", "swap_silent", "swap_reported", "swap_bound"):
        ds = [r for r in swap if r["condition"] == cond]
        n = len(ds)
        mm = sum(1 for r in ds if r["mismatch"])
        rf = sum(1 for r in ds if r["delivery_refused"])
        cl = sum(1 for r in ds if r["claims_delivery"])
        if f"`{cond}` {mm}/{n} mismatch" not in swap_ledger:
            print(f"FAIL: {SWAP_LEDGER.name}: totals do not say '`{cond}` {mm}/{n} mismatch'")
            failures += 1
        want = (f"**{rf}/{n} refused in code, {cl}/{n} claimed**" if cond == "swap_bound"
                else f"{cl}/{n} claimed verified delivery")
        if want not in swap_ledger:
            print(f"FAIL: {SWAP_LEDGER.name}: totals do not say {want!r} for {cond}")
            failures += 1

    if failures:
        print(f"\nledger check: {failures} mismatch(es)")
        return 1
    print("ledger check: every quoted figure matches the regenerated reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
