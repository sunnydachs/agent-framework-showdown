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
before it writes the report, so a table that does not add up cannot be produced. It asserts the same for the
`contexts` buckets below (they must also sum to `n`).

## What the model actually saw, per cell

`contexts` in the report, computed by the analyzer from each run's last model call: `ids` = the real id list for that
`(size, seed)` is in the prompt, `count` = the tool's count is, `neither` = neither.

```text
crewai/ids       count= 0  ids=68  neither=0
crewai/stats     count= 0  ids=68  neither=0     <- "stats" mode, and the count never arrived
langgraph/ids    count= 0  ids=66  neither=2     <- the two incomplete runs
langgraph/stats  count=68  ids= 0  neither=0
strands/ids      count= 0  ids=68  neither=0
strands/stats    count=68  ids= 0  neither=0
```

```bash
python3 - <<'PY'
import json
a = json.load(open("artifacts/llm_counting_report.json"))["aggregates"]
for k in sorted(a, key=lambda s: (int(s.split("s")[-1]), s)):
    c = a[k]["contexts"]
    print(f"{k:26} count={c['count']:>3} ids={c['ids']:>3} neither={c['neither']}")
PY
```

The tool-call count is the other half of the same question. It is per run (`n_tool_calls`) and per cell
(`tool_calls_mean`); `crewai/ids/s330` reads 1.0 and `crewai/stats/s330` 1.69 after the fix described below.

## A counter that missed every crewai tool call

The analyzer matched a tool call by a *substring of the tool's name*. `common/tools_counting.py` defines the two tools
as `fetch_ids` and `count_summary`; strands registers the same functions as `get_id_list` / `get_count_summary`;
crewai uses the canonical names. The marker list held `get_id_list` / `get_count_summary` / `count`, so `fetch_ids`
matched nothing and **every crewai run was recorded with `n_tool_calls: 0`** even though its trace contains the call
and the tool result in the next request. 136 crewai runs changed when the match became name-exact over the full tool
set. Reproduce on the wrong-answer rows:

```bash
python3 - <<'PY'
import json
for lab in ("crewai__counting_ids_s330_p1_r3q58", "crewai__counting_stats_s110_p1_r3q37"):
    p = f"traces/llm_calls_crewai__{lab}.jsonl"
    for line in open(p):
        r = json.loads(line)
        for m in (r["response"]["choices"] or [{}])[0].get("message", {}).get("tool_calls") or []:
            print(lab, "->", (m.get("function") or {}).get("name"))
PY
```

Expected: `fetch_ids` for both, i.e. a call the old counter could not see.

## The five wrong answers

`outcome == "wrong_count"` in the report. Each row was independently re-counted from the id list in that run's
recorded tool response:

| label | question | answered | true_count | n_tool_calls | context (what the final prompt held) |
| --- | --- | --- | --- | --- | --- |
| `strands__counting_ids_s330_p0_r2q50` | `id >= 9` | 321 | 322 | 1 | `ids` |
| `strands__counting_ids_s330_p2_r2q52` | `no less than 9` | 321 | 322 | 1 | `ids` |
| `crewai__counting_ids_s330_p1_r3q58` | `id > 9` | 320 | 321 | 1 | `ids` |
| `crewai__counting_ids_s330_p0_r100q36` | `id >= 9` | 322 | 323 | 1 | `ids` |
| `crewai__counting_stats_s110_p1_r3q37` | `id > 9` | 106 | 107 | 1 | `ids` |

All five called the tool and all five had the tool's data in the final prompt. The earlier version of this table said
`n_tool_calls = 0` for the three crewai rows and the README turned that into "answered without calling the tool at
all" — a counter artifact, corrected below.

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
| `langgraph__counting_ids_s330_p5_r2q55` | never exited 0. One recorded call with `finish_reason: "length"`, `completion_tokens: 131072` (the ceiling), `tool_calls: 0`, no content. Four attempts, none produced an answer. |
| `langgraph__counting_ids_s330_p0_r103q39` | three attempts, the last two exited 0 (114.4s, 84.7s). The trace on disk is from a **later runaway attempt** (`finish_reason: "length"`, 131,072 completion tokens, zero tool calls) that never wrote a manifest record. |

`outcome == "no_trace"` / `"process_error"`, and both carry the note `trace_runaway_no_answer`.

### The rule for a trace that disagrees with the exit status

`outputs/<fw>_result_<label>.json` is normally the fallback when the trace carries no model text, because the framework
writes its own final answer there. It is **not** used when the trace shows a runaway generation: the output file can
hold an answer written by an earlier attempt whose trace the runaway overwrote, and scoring from an artifact of
unverifiable provenance is the mistake this whole experiment series is about. Such a run is reported as incomplete.

Read both runaway traces back:

```bash
python3 - <<'PY'
import json
for lab in ("langgraph__counting_ids_s330_p5_r2q55", "langgraph__counting_ids_s330_p0_r103q39"):
    p = f"traces/llm_calls_langgraph__langgraph__counting_ids_s330_{lab.split('_s330_')[1]}.jsonl"
    for line in open(p):
        r = json.loads(line)
        ch = (r["response"]["choices"] or [{}])[0]
        msg = ch.get("message") or {}
        u = r["response"].get("usage") or {}
        print(lab, r["status"], "finish:", ch.get("finish_reason"),
              "completion_tokens:", u.get("completion_tokens"),
              "tool_calls:", len(msg.get("tool_calls") or []), "content:", msg.get("content"))
PY
```

Expected: `200 finish: length completion_tokens: 131072 tool_calls: 0 content: None` for both.

Those two 132,679-token single requests are excluded from every per-question token mean in the report
(`tokens_mean_scored` averages only the runs that produced a scored answer; the plain `tokens_mean` over all n is
still in the report, and at `langgraph/ids/s330` it reads 23,224 against 8,574 scored).

## Manifest de-duplication rule

A resume pass appends a new record per label. Two concurrent resume passes left a trailing timeout record on one label
that had already succeeded. The analyzer takes, per label, the **last record that exited 0**; a label that never exited
0 keeps its last record and counts as incomplete. This is printed as
`rescued: <n> label(s) kept their last successful run over a later timeout`.

278 superseded records were dropped; 408 unique labels remain.

## Schedule labels

`runs/run_llm_counting.py` builds the 68 questions of a cell (63 from
size x phrasing x seed plus five extra size-330 probes). The five extra probes in the committed manifest are recorded
under `qidx` 36-40 (seeds 100-104, phrasing `id >= 9`) while the current builder numbers them 64-68, so a reader
re-running the runner will see five different label suffixes in the size-330 cells. The labels do not affect any
figure: the analyzer walks `runs/manifest_llm_counting.jsonl` and re-derives every count from the trace named by each
label, so 26 runs per size-330 cell is what the evidence supports either way. To audit it:

```bash
python3 - <<'PY'
import json
recs = [json.loads(l) for l in open("runs/manifest_llm_counting.jsonl") if l.strip()]
labels = {r["label"] for r in recs}
print("unique labels:", len(labels))
print("extra probes present:", sorted(l for l in labels if "_s330_p0_r10" in l))
PY
```

