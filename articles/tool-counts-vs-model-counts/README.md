# When the tool returns the rows — article evidence

Evidence for the experiment *"the tool returns the rows, the model does the counting"* (candidate article A).

The claim: at 330 rows each of the three frameworks ends at 92.3% — but **not for the same reason**: the two
model-driven frameworks lose two runs to off-by-one answers, while the graph framework loses two runs to a
generation that never answered at all. Where the framework carries the tool's precomputed `count` through to the
model, the answer is 100% for a fraction of the tokens — in the framework that keeps the list inside code-managed
state the per-question cost at 330 rows drops from 8,574 to 143, 60x. In the third framework the count never reached
the model at all, so its `stats` column is a second sample of the same list-counting task, at list-level cost.

The measurement is `runs/analyze_llm_counting.py` over the traces in `traces/`. One recording proxy sits between every
framework and the endpoint, so all frames in the matrix are diffed from the same wire format.

## The grid

3 frameworks x 2 modes x 3 list sizes x 7 threshold phrasings x 3 seeds.

- mode `ids`   — the tool is asked for the id list only; the model must count
- mode `stats` — the tool is asked for precomputed `count` / `min` / `max`
- sizes 11 / 110 / 330 ids, phrasings such as `id >= 9`, `id > 9`, `no less than 9`, `greater than 5 and less than 9`

**A mode label says what the tool was ASKED for, not what the framework carried through to the model.** The analyzer
therefore classifies every run by what its last model call actually had in front of it — the id list (a string test
against the real ids for that `(size, seed)`) or the tool's count — and reports it per cell as `contexts`. That
measurement is why one framework's `stats` column cannot be read as "the tool counted":

| cell | n | the count reached the model | the id list reached the model | neither | no final prompt |
| --- | --- | --- | --- | --- | --- |
| crewai `ids` | 68 | 0 | 68 | 0 | 0 |
| crewai `stats` | 68 | **0** | **68** | 0 | 0 |
| langgraph `ids` | 68 | 0 | 66 | 0 | 2 |
| langgraph `stats` | 68 | 68 | 0 | 0 | 0 |
| strands `ids` | 68 | 0 | 68 | 0 | 0 |
| strands `stats` | 68 | 68 | 0 | 0 | 0 |

(`no final prompt` is the two langgraph `ids` runs that produced no answer at all.)

408 runs (21 per cell at sizes 11 and 110, 26 at 330 where five extra probes are added). 407 exited 0. Two runs
produced no answer at all, both `langgraph` in `ids` at size 330 on the phrasing `id >= 9`: the model generated
**131,072 completion tokens in a single call — the completion ceiling — with zero tool calls**, `finish_reason: length`,
and no content. One of the two had an earlier attempt that exited 0 in 84.7s; the trace on disk belongs to the runaway
attempt, and the analyzer reports that run as incomplete rather than scoring it from the framework's own output file,
whose provenance cannot be checked. Both are listed as incomplete and never folded into count%.

## Result at 330 rows

| framework | model counts (`ids`) | tool counts (`stats`) | tokens/question `ids` | tokens/question `stats` | what the model actually saw in `stats` |
| --- | --- | --- | --- | --- | --- |
| crewai | 92.3% (24/26, 2 wrong) | 100% (26/26) | 14,600 | 12,565 | the id list, every run |
| langgraph | 92.3% (24/26, 2 incomplete) | 100% (26/26) | 8,574 | 143 | the count, every run |
| strands | 92.3% (24/26, 2 wrong) | 100% (26/26) | 11,528 | 1,418 | the count, every run |

92.3% is the same number three times and the same failure twice: crewai and strands each answered two runs one or two
off, while langgraph's two missing runs produced no answer at all. Any sentence of the form "all three failed the same
way" is wrong; the rate coincides, the mechanism does not.

Crewai's `stats` cell cost 12,565 tokens against the 143 and 1,418 of the two frameworks that handed the count over,
because in crewai the tool's count never reached the model while the list did. Read crewai's `ids` and `stats` columns
as two samples of one task (24/26 vs 26/26, no design change between them), not as the two tool designs.

Token figures are the mean over the runs that produced a scored answer. The two incomplete runs are excluded: one
recorded 132,679 tokens for a single runaway call and would otherwise triple `langgraph`'s per-question cost.

At 11 and 110 rows every framework is at 100% in both modes, with one exception: crewai in `stats` at 110 rows
answered 106 where the true count was 107 — with the list in front of it. 18 of its 26 size-330 `stats` runs did call
the counting tool; the answer still came from the list.

## What the five wrong answers actually were

Every wrong answer is off by one or two; none is a wrong query. Each was re-checked against the id list recorded in
that run's tool response, not against the analyzer's own number. **All five called the tool** (`n_tool_calls: 1`) and
the tool's data was in the final prompt of all five — the failure is in reading the data, not in fetching it.

| run | asked | answered | true | tool calls | what the final prompt held |
| --- | --- | --- | --- | --- | --- |
| strands `ids` s330 `id >= 9` | 322 | 321 | 322 | 1 | the id list (tool result in the conversation) |
| strands `ids` s330 `no less than 9` | 322 | 321 | 322 | 1 | the id list |
| crewai `ids` s330 `id > 9` | 321 | 320 | 321 | 1 | the id list (relayed from the previous task) |
| crewai `ids` s330 `id >= 9` | 323 | 322 | 323 | 1 | the id list |
| crewai `stats` s110 `id > 9` | 107 | 106 | 107 | 1 | the id list, not the count |

An earlier revision of this ledger said "three of those runs answered without calling the tool at all". That was an
artifact of the tool-call counter, not a behaviour — see the pitfalls below.

## Two measurement bugs found while reviewing this ledger

1. **A tool-call counter that knew only some of the tool names.** The analyzer counted a call only when the tool's
   *name* contained one of `get_id_list` / `get_count_summary` / `count`. Crewai registers the same functions as
   `fetch_ids` / `count_summary`, so **every crewai run was recorded with `n_tool_calls: 0`** while its trace held the
   call and the tool result. After matching the tool by identity (all four names are known now), 136 crewai runs
   changed: `crewai/ids/s330` from 0.0 to 1.0 tool calls per run, `crewai/stats/s330` from 0.69 to 1.69. Fix the
   counter before quoting it — a claim built on it had already reached a draft.
2. **A mode label read as a behaviour.** The matrix was described as "the tool counts" for the whole `stats` column.
   The traces say the model in crewai's `stats` runs never received a count. What the tool *returns* and what the
   framework *carries into the prompt* are different facts, and only the second explains the answers and the cost.

## Reproduce

```bash
python3 runs/analyze_llm_counting.py    # -> artifacts/llm_counting_report.json
```

The analyzer reads `runs/manifest_llm_counting.jsonl` and the 408 traces, recomputes the true count from the id list
in each recorded tool response, classifies what each final prompt actually contained, and prints the matrix above.
`evidence.md` in this directory carries the per-cell table and the recompute commands.

## Limits

- One model across all runs. The count% figures are a matrix over framework x mode, not a model ranking.
- 21-26 runs per cell. A two-run gap is not a design effect, and crewai's `ids`-vs-`stats` gap is exactly that size.
- The two incomplete runs are runaway generations, not scored failures: they are listed separately and never folded
  into count%. Their cost (132,679 tokens for one call) is likewise excluded from the per-question token means.
- The recorder forwards to a single shared endpoint, so a rate-limited response can appear on any framework; runs
  that hit it are recorded as such and are excluded from the scored percentages.
- `contexts` is a string test against the ids for that `(size, seed)` and the tool's count, not a semantic diff of the
  prompt: a framework that reformatted the ids (spacing, truncation) would land in `neither`. None did.
