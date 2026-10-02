# When the tool returns the rows — article evidence

Evidence for the experiment *"the tool returns the rows, the model does the counting"* (candidate article A).

The claim: at 330 rows, all three frameworks let the final answer drift by one or two, and the drift is identical
across frameworks — so this failure is not something the framework layer absorbs. Give the same tool a precomputed
`count` instead of the raw list and every framework lands at 100% for a fraction of the tokens: in the framework that
keeps the list inside code-managed state, the per-question token cost at 330 rows drops from 8,574 to 143 — 60x.

The measurement is `runs/analyze_llm_counting.py` over the traces in `traces/`. One recording proxy sits between every
framework and the endpoint, so all frames in the matrix are diffed from the same wire format.

## The grid

3 frameworks x 2 modes x 3 list sizes x 7 threshold phrasings x 3 seeds.

- mode `ids`   — the tool returns only the id list; the model must count
- mode `stats` — the tool precomputes `count` / `min` / `max`; the model reports them back
- sizes 11 / 110 / 330 ids, phrasings such as `id >= 9`, `id > 9`, `no less than 9`, `greater than 5 and less than 9`

408 runs (21 per cell at sizes 11 and 110, 26 at 330 where five extra probes are added). 407 exited 0; one
(langgraph, `ids`, size 330, wording `greater than 5 and less than 9`) never produced a trace and is reported as
incomplete rather than as a wrong answer.

## Result at 330 rows

| framework | model counts (`ids`) | tool counts (`stats`) | tokens/question `ids` | tokens/question `stats` |
| --- | --- | --- | --- | --- |
| crewai | 92.3% (24/26) | 100% (26/26) | 14,600 | 12,565 |
| langgraph | 92.3% (24/26, 2 incomplete) | 100% (26/26) | 8,574 | 143 |
| strands | 92.3% (24/26) | 100% (26/26) | 11,528 | 1,418 |

Token figures are the mean over the runs that produced a trace (the incomplete runs recorded no tokens at all and
would otherwise dilute the mean).

At 11 and 110 rows every framework is at 100% in both modes, with one exception: crewai in `stats` at 110 rows
answered 106 where the true count was 107.

## What the five wrong answers actually were

Every wrong answer is off by one or two; none is a wrong query. Each was re-checked against the id list recorded in
that run's tool response, not against the analyzer's own number.

| run | asked | answered | true | tool calls |
| --- | --- | --- | --- | --- |
| strands `ids` s330 `id >= 9` | 322 | 321 | 322 | 1 |
| strands `ids` s330 `no less than 9` | 322 | 321 | 322 | 1 |
| crewai `ids` s330 `id > 9` | 321 | 320 | 321 | 0 |
| crewai `ids` s330 `id >= 9` | 323 | 322 | 323 | 0 |
| crewai `stats` s110 `id > 9` | 107 | 106 | 107 | 0 |

Two of those runs answered **without calling the tool at all** (`tool calls = 0`), including the one in `stats` mode
where the correct number was sitting in the tool result the model never fetched.

## Reproduce

```bash
python3 runs/analyze_llm_counting.py    # -> artifacts/llm_counting_report.json
```

The analyzer reads `runs/manifest_llm_counting.jsonl` and the 383 traces, recomputes the true count from the id list
in each recorded tool response, and prints the matrix above. `evidence.md` in this directory carries the per-cell
table and the recompute commands.

## Limits

- One model across all runs. The count% figures are a matrix over framework x mode, not a model ranking.
- 21-26 runs per cell.
- The single incomplete run is an infrastructure timeout on the free tier, not a scored failure; it is listed
  separately and never folded into count%.
- The recorder forwards to a single shared endpoint, so a rate-limited response can appear on any framework; runs
  that hit it are recorded as such and are excluded from the scored percentages.
