# Exit 0 is not a test result — article evidence

Evidence for the article *"Exit 0 is not a test result: 3 silent agent failures"* (English, dev.to) /
「AIエージェントが「成功」と言って何もしない」 (Japanese, note).

The claim: a framework's success signal — exit code 0, a "task complete" status line — is not evidence that the work
happened. Three shapes of that failure are measured in the **schema-change harshness ladder (experiment 5H)**, which is
`runs/analyze_harsh.py` over the traces in `traces/`.

| # | Shape | Measured |
| --- | --- | --- |
| 1 | The verification never ran and the run still reported success | 6/6 runs (Strands 3/3, CrewAI 3/3) exited 0 with `verified = 0/3`; at the argument-type level Strands took 2, 1 and 5 tool error responses on the wire and still exited 0 |
| 2 | The model invented a required argument and the tool accepted it | 6/6 runs (Strands 3/3, CrewAI 3/3); the tool's only validation was "non-empty string" |
| 3 | The visible answer was empty while the run exited 0 | 2 runs, Strands only; the draft was in the last tool-call argument (100 and 106 words) |

## Reproduce

The aggregate reports are not committed (see `.gitignore`); regenerate them from the published traces first.

```bash
python3 runs/analyze_harsh.py          # -> artifacts/schema_harshness_report.json
python3 - <<'PY'
import json
a = json.load(open("artifacts/schema_harshness_report.json"))["aggregates"]
for cell in ("strands/remove", "crewai/remove", "strands/add", "crewai/add"):
    v = a[cell]
    print(f"{cell:<16} n={v['n']} verified={v['verified']} silent_failure={v['silent_failure']}")
PY
```

Expected:

```text
strands/remove   n=3 verified=0 silent_failure=3
crewai/remove    n=3 verified=0 silent_failure=3
strands/add      n=3 verified=3 silent_failure=0
crewai/add       n=3 verified=3 silent_failure=0
```

`evidence.md` in this directory lists every number the article uses, with its source file and a recompute command
(including the two shapes that are read straight from the traces rather than from an aggregate report).

## What the recording shows that a status line does not

- The 2/1/5 "tool errors" are application-level domain errors — `{"error": "document 88 not found"}` — returned on calls
  the schema accepted (`runs/analyze_harsh.py` counts them separately from `schema_errors_seen`, which is 0 in those runs).
- The invented `note` argument differs per run in Strands (three distinct sentences) and repeats verbatim in all three
  CrewAI runs; the wire is the only place that shows where the text came from.
- Where a publish step and a duplicate effect are involved, that is the crash/idempotency run set (`cell_b_idempotency`),
  not this ladder: with a key derived from the argument bytes, a reworded retry is not recognised as a duplicate and the
  effect runs twice (`n_publish_execs = 2`, `deduped = 0`; with a position key the same shape deduped once).

## Limits

- 3 runs per cell is a trend check, not a statistical claim.
- One model across all runs.
- The two modelled frameworks did not advertise the new parameter identically, and one sampled at temperature 0, so
  "one variant differed per run, the other repeated" has more than one plausible cause.
