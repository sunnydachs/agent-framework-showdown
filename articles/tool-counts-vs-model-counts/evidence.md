# evidence — tool returns rows vs count

Every number below is recomputed from the committed traces by `runs/analyze_llm_counting.py`. Nothing here is copied
from a summary: the analyzer re-derives the true count from the id list inside each run's recorded tool response.

## Source of each number

| number | source |
| --- | --- |
| run schedule, exit status | `runs/manifest_llm_counting.jsonl` |
| prompts, tool calls, tool results, tokens, finish reasons | `traces/llm_calls_<framework>__<label>.jsonl` |
| the framework's own final answer | `outputs/<framework>_result_<label>.json` |
| true count per question | recomputed from the id list in the recorded tool response |
| aggregates | `artifacts/llm_counting_report.json` (regenerated, not committed) |

## Recompute

```bash
python3 runs/analyze_llm_counting.py
python3 - <<'PY'
import json
a = json.load(open("artifacts/llm_counting_report.json"))["aggregates"]
for k in sorted(a, key=lambda s: (int(s.split("s")[-1]), s)):
    v = a[k]
    print(f"{k:26} n={v['n']:>3} correct={v['correct']:>3} wrong={v['wrong_count']} "
          f"incomplete={v['incomplete']} tokens_mean={v['tokens_mean']}")
PY
```

## Full grid (all eighteen cells)

```text
crewai/ids/s11               n= 21 correct= 21 wrong=0 incompl=0 tok_scored=1422
crewai/stats/s11             n= 21 correct= 21 wrong=0 incompl=0 tok_scored=3376
langgraph/ids/s11            n= 21 correct= 21 wrong=0 incompl=0 tok_scored=210
langgraph/stats/s11          n= 21 correct= 21 wrong=0 incompl=0 tok_scored=138
strands/ids/s11              n= 21 correct= 21 wrong=0 incompl=0 tok_scored=943
strands/stats/s11            n= 21 correct= 21 wrong=0 incompl=0 tok_scored=1401
crewai/ids/s110              n= 21 correct= 21 wrong=0 incompl=0 tok_scored=4738
crewai/stats/s110            n= 21 correct= 20 wrong=1 incompl=0 tok_scored=7432
langgraph/ids/s110           n= 21 correct= 21 wrong=0 incompl=0 tok_scored=1908
langgraph/stats/s110         n= 21 correct= 21 wrong=0 incompl=0 tok_scored=148
strands/ids/s110             n= 21 correct= 21 wrong=0 incompl=0 tok_scored=2885
strands/stats/s110           n= 21 correct= 21 wrong=0 incompl=0 tok_scored=1418
crewai/ids/s330              n= 26 correct= 24 wrong=2 incompl=0 tok_scored=14600
crewai/stats/s330            n= 26 correct= 26 wrong=0 incompl=0 tok_scored=12565
langgraph/ids/s330           n= 26 correct= 24 wrong=0 incompl=2 tok_scored=8574
langgraph/stats/s330         n= 26 correct= 26 wrong=0 incompl=0 tok_scored=143
strands/ids/s330             n= 26 correct= 24 wrong=2 incompl=0 tok_scored=11528
strands/stats/s330           n= 26 correct= 26 wrong=0 incompl=0 tok_scored=1418
```

`tok_scored` is the mean over the runs that produced a trace (`tokens_mean_scored` in the report); the plain
`tokens_mean` over all n is also in the report and is lower wherever a run recorded no tokens.

Row check: `correct + wrong_count + incomplete == n` for every cell. The analyzer asserts this over the whole table
before it writes the report, so a table that does not add up cannot be produced.

## The five wrong answers

`outcome == "wrong_count"` in the report. Each row was independently re-counted from the id list in that run's
recorded tool response:

| label | question | answered | true_count | n_tool_calls |
| --- | --- | --- | --- | --- |
| `strands__counting_ids_s330_p0_r2q50` | `id >= 9` | 321 | 322 | 1 |
| `strands__counting_ids_s330_p2_r2q52` | `no less than 9` | 321 | 322 | 1 |
| `crewai__counting_ids_s330_p1_r3q58` | `id > 9` | 320 | 321 | 0 |
| `crewai__counting_ids_s330_p0_r100q36` | `id >= 9` | 322 | 323 | 0 |
| `crewai__counting_stats_s110_p1_r3q37` | `id > 9` | 106 | 107 | 0 |

Two independent spot checks of the true count, counted straight from the tool response in the trace:

```bash
python3 - <<'PY'
import json, re
for lab in ("strands__counting_ids_s330_p0_r2q50", "crewai__counting_ids_s330_p0_r100q36"):
    raw = open(f"traces/llm_calls_{lab.split('__')[0]}__{lab}.jsonl").read()
    ids = None
    for line in raw.splitlines():
        rec = json.loads(line)
        for m in ((rec.get("request") or {}).get("messages") or []):
            if m.get("role") == "tool":
                nums = [int(x) for x in re.findall(r"\b\d+\b", str(m.get("content"))) if 0 < int(x) < 1000]
                if len(nums) > 100:
                    ids = nums
    print(lab, "ids:", len(ids), ">=9:", sum(1 for x in ids if x >= 9), ">9:", sum(1 for x in ids if x > 9))
PY
```

Expected: 330 ids, `>=9` = 322 and 323 respectively — matching the analyzer's `true_count` and both 1 above what the
model answered.

## Incomplete runs

| label | why |
| --- | --- |
| `langgraph__counting_ids_s330_p5_r2q55` | never exited 0 (240s cap on the free tier, three attempts); no trace file |

`outcome == "no_trace"` / `"process_error"`.

## Manifest de-duplication rule

A resume pass appends a new record per label. Two concurrent resume passes left a trailing timeout record on one label
that had already succeeded. The analyzer takes, per label, the **last record that exited 0**; a label that never exited
0 keeps its last record and counts as incomplete. This is printed as
`rescued: <n> label(s) kept their last successful run over a later timeout`.

278 superseded records were dropped; 408 unique labels remain.
