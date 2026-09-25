# agent-framework-showdown

**The same digest agent built three times — in Strands, LangGraph, and CrewAI — with every LLM call recorded, so you can compare how they actually behave.**

English | [日本語](README.ja.md)

Same task. Same model. Same tools. Three frameworks. Twenty-seven runs. All LLM traffic captured through a local recorder, so "which framework behaves differently" is an answer backed by trace files instead of vibes.

## The task

A tech-news digest agent:

1. collect 5 headlines via a `fetch_headlines` tool
2. write a ~100-word digest
3. verify the word count via a `word_count` tool, revising if out of band

All three frameworks hit the same model behind a local recorder proxy, so the logs are directly comparable.

## How to run

```bash
# one venv per framework (Python 3.12 - CrewAI requires <3.14)
uv venv .venv-strands   --python 3.12 && uv pip install --python .venv-strands/bin/python   "strands-agents[litellm]"
uv venv .venv-langgraph --python 3.12 && uv pip install --python .venv-langgraph/bin/python langgraph langchain-openai
uv venv .venv-crewai    --python 3.12 && uv pip install --python .venv-crewai/bin/python    crewai
```

Create a `.env` with your LLM credentials (any OpenAI-compatible endpoint):

```bash
LLM_API_KEY=sk-...
LLM_BASE_URL=https://your-openai-compatible-endpoint.example.com
```

Then:

```bash
# 1. start the recorder (terminal 1)
python3 proxy/rec_proxy.py --port 8118

# 2. run each framework (terminal 2), clearing traces/ between runs
rm -f traces/*.jsonl
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 ./.venv-strands/bin/python   frameworks/strands_digest.py
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 OPENAI_API_KEY=dummy-key ./.venv-langgraph/bin/python frameworks/langgraph_digest.py
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 OPENAI_API_KEY=dummy-key CREWAI_TELEMETRY=false OTEL_SDK_DISABLED=true ./.venv-crewai/bin/python frameworks/crewai_digest.py

# 3. aggregate
python3 proxy/parse_sse.py
python3 proxy/report.py
```

For the reproducibility matrix (27 runs: 3 frameworks x 3 scenarios x 3 runs):

```bash
python3 runs/run_matrix.py
python3 runs/analyze_matrix.py   # -> artifacts/matrix_report.json
```

For the follow-up experiments (45 more runs, all through the same proxy):

```bash
# A: framework tax - what each framework ADDS to the first LLM call
python3 runs/analyze_tax.py

# B: task-shape scaling - complex task (branch + 2 fetches) vs base, 9 runs
python3 runs/run_complex.py && python3 runs/analyze_scaling.py

# D: human-in-the-loop - interrupt() vs human_input vs prompt-only, 18 runs
python3 runs/run_hitl.py && python3 runs/analyze_hitl.py

# E: audit-trail reconstruction - what an auditor can recover from the traces
python3 runs/analyze_audit.py

# F: structured-output compliance - strict JSON, 9 runs
python3 runs/run_structured.py && python3 runs/analyze_structured.py

# G: crash recovery + idempotency + audit-under-retry (34 runs)
#    SIGKILL mid-interrupt vs no checkpointer; position-key vs content-hash
#    idempotency vs none; whether an auditor can detect duplicate effects
python3 runs/run_crash_idem.py && python3 runs/analyze_crash_idem.py
```

## Measured numbers (Sep 2026, single model, 27 runs)

|                       | Strands              | LangGraph            | CrewAI      |
|-----------------------|----------------------|----------------------|-------------|
| Lines of code         | 78                   | 115                  | 110         |
| LLM calls             | 3-5 (adaptive)       | 1 (base) / 2 (tight) | 4 fixed     |
| Total tokens (base)   | 2,370                | 2,007                | 2,532       |
| Total LLM latency     | 4.2s                 | 4.7s                 | 3.8s        |
| venv size (packages)  | 262MB (81)           | 71MB (45)            | 699MB (142) |

### Output stability (word-count spread across 3 runs, max - min)

| Scenario              | Strands | LangGraph | CrewAI |
|-----------------------|---------|-----------|--------|
| base (80-120 words)   | 15      | **13**    | **0**  |
| tight (95-105 words)  | 11      | **3**     | 2      |
| drift (schema rename) | 12      | 16        | 0      |

### What the traces show

- **LangGraph** in base mode made a single LLM call and wrote the draft in one shot — word-count spread was 13 words. Switching to the tight scenario fired the explicit verify/revise loop and cut the spread to 3 (−77%), at the cost of 2.5x tokens (2,007 -> 5,262) and 2.5x latency (4.7s -> 11.8s). **Explicit control buys determinism — and you pay for it in tokens and latency.**
- **CrewAI** produced byte-identical output across all 3 base and drift runs (96/96/96 words). temperature=0 plus the role prompt dominates; the tradeoff is a fixed 4-call structure with no flexibility.
- **Strands** self-corrected inside its own loop: the model noticed a 77-word draft, judged it under the floor, and revised itself to 104 — with the call count varying per run ([5, 3, 4]). Model-driven control bought adaptability directly, and the model deciding when to stop is part of the design.

### Schema-drift resilience

The `word_count` tool's argument was renamed (`text` -> `content`). All three frameworks' models followed the **new** schema with zero wrong-arg calls; no error recovery was triggered. (LangGraph would have been immune anyway — its tool calls live in code, not in a prompt.)

## Experiment 4 (G): crash recovery, idempotency, and audit-under-retry

34 more runs, same proxy, same model. Three questions: does state survive process death, do idempotency keys prevent duplicate side effects when an LLM retries, and can an auditor prove what happened from the traces alone. Full data: `artifacts/crash_idem_report.json` (rebuild with `runs/run_crash_idem.py && runs/analyze_crash_idem.py`).

### Crash-resume (SIGKILL mid-approval-wait, new process resumes)

| Framework | persistence | resume | state survived | LLM calls to resume |
| --- | --- | --- | --- | --- |
| LangGraph | durable checkpointer | **0.01-0.02s** | 3/3 | **0** (state restored, no re-inference) |
| LangGraph | no checkpointer | 0.0s | 0/3 | - (state died with the process) |
| Strands | none built-in | 4.9s avg | re-run from scratch | 5.3 avg |
| CrewAI | none for agents | 4.2s avg | re-run from scratch | 2.0 avg |

A durable checkpointer is the difference between *resume* and *redo*. LangGraph's 0.01s resume is the checkpointer restoring the graph — no LLM call at all. Without it, an identical-looking "resume" is a full re-run paying full token cost again.

The issue-8764 shape (crash before the first durable checkpoint): on the tested LangGraph version the empty-thread resume **succeeded without raising** instead of raising `EmptyInputError` — `Command(resume=...)`, `invoke(None)`, and a MemorySaver resume all silently re-ran the graph (1 extra LLM call measured), while a crash inside the first node still leaves the durable input checkpoint, so the error window exists only before that first write. The failure-record gap is version-dependent: don't rely on the error either way — keep an external acceptance ledger.

### Idempotency (retry re-executes: average duplicate executions per retry)

| key strategy | same-args retry | reworded retry |
| --- | --- | --- |
| position key (`workflow:step:tool`) | 1 dup, all deduped | 3 dups avg, **33% deduped** (2.67 caller-bug rejections) |
| content hash (sha256 of args) | 1 dup, all deduped | **1 dup, 0% deduped — the hash changed, the dedup missed** |
| no key | 1.33 dups, 0% deduped | 1 dup, 0% deduped |

The core result: **a content-hash key silently fails exactly when the model rewords the arguments on retry** — which is what LLM retries do (they re-reason, not replay). A position-derived key survives rewording because it identifies the *intent* (workflow position), not the bytes. Every duplicate carried a distinct tool_call ID on the wire, so nothing at the protocol layer would have caught them.

### Audit-under-retry (trace-only auditor, 8th fact: duplicate detection)

The proxy records every attempt, so per-run audit recovery stayed at 100% for rationale, duplicate visibility, dedup provability, and retry evidence across all six cells. An auditor reading only the traces can see the duplicate, see which attempt was deduped, and see why (the ledger result is in the tool response) — but only because the recording is at the wire level. Framework-level trace surfaces would not show the double-fire at all.

## Experiment 5 (H): schema-change harshness

36 more runs (3 frameworks x 4 harshness levels x 3 runs), same proxy, the same model across all runs. This answers the question the rename result raised: rename was not "the first schema change we tried" — it was the one that survived, and it was the *last* level that did. The word_count tool's signature was changed four ways, with the task prompt held fixed across all of them:

| level | schema the model sees | what changed |
| --- | --- | --- |
| rename | `word_count(content: str)` | argument renamed (the original drift, replicated as the ladder's baseline) |
| type | `word_count(content: int)` | the argument is now a numeric document id — a string payload violates the type |
| remove | `word_count()` | the text argument is deleted; the tool returns a static placeholder count |
| add | `word_count(content: str, note: str)` | a NEW required argument the prompt never mentions |

Full data: `artifacts/schema_harshness_report.json` (rebuild with `runs/run_harsh.py && runs/analyze_harsh.py`).

### Results (3 runs per cell)

Outcome per cell. "verified" = the digest's word count was actually checked against a real count of the digest:

| level | Strands | LangGraph | CrewAI |
| --- | --- | --- | --- |
| rename | 3/3 verified, 0 errors | 3/3 verified | 3/3 verified |
| type | 3/3 exit 0, **0/3 verified (silent)** | **3/3 crash** in the verify node | **3/3 dead** (provider 400 mid-recovery) |
| remove | 3/3 exit 0, **0/3 verified (silent)** | **3/3 crash** | 3/3 exit 0, **0/3 verified (silent)** |
| add | 3/3 verified (invented `note`) | **3/3 crash** | 3/3 verified (invented `note`) |

Mechanics per framework:

| level | framework | wrong-arg calls | tool-layer error responses | LLM calls per run | tokens (mean) |
| --- | --- | --- | --- | --- | --- |
| type | Strands | 2 | 10 (2 schema + 8 "document not found") | [4, 3, 9] | 6,004 |
| type | LangGraph | - (crash before any tool traffic) | - | [1, 1, 1] | 1,934 |
| type | CrewAI | 9 | 9 (JSON parse failures) | [8, 8, 8] | 3,394 |
| remove | Strands | 1 | 0 | [4, 5, 4] | 4,201 |
| remove | CrewAI | 0 | 0 | [6, 5, 4] | 4,331 |

- **Strands degrades silently.** At `type` the model genuinely tried to comply with the integer schema — it sent numeric document ids, got "document not found" errors back, and then output the digest anyway: exit 0, verification never happened, no error surfaced. At `remove` it accepted the static 8-word placeholder as a successful check in 3/3 runs (one run re-checked three times, apparently suspicious of the count, and still finished "successfully"). The error-and-retry loop is not free: mean tokens at `type` were 6,004 vs 2,505 at `rename` (2.4x).
- **LangGraph fails loudly.** Its tools are invoked in code, so a signature change that is not reflected at the call site raises a `TypeError` inside the verify node: 9/9 runs at type/remove/add died with the draft written but no result produced (each run got exactly as far as the one draft-writing LLM call, then crashed at verification). A silent failure is essentially impossible — the trade is a total outage that is trivially detectable by a process monitor.
- **CrewAI does both.** At `type` the model stuffed the draft text into the integer field as unparseable JSON (9 wrong-arg calls across 3 runs), the tool layer returned parse errors, and the follow-up request carrying those errors was rejected by the provider with a 400 — the run died loudly, but in the middle of recovery, not at the schema mismatch itself. At `remove` it matched Strands: believed the static count, exited 0, no verification.
- **`add` was the one survivable harsh change for model-driven frameworks:** 6/6 Strands/CrewAI runs invented a plausible value for the never-documented `note` argument (e.g. "Draft digest of AI agents news") and real verification resumed. A schema change the model can *infer* from the schema itself is absorbable; a change that contradicts the prompt (type) or removes the verification path entirely (remove) is not.

So the direct answer to the reader question: rename was the change that survived *because it was the only one we had tried* — and replicating it here as the baseline, it survived again (9/9). The first harsher change (type) broke all three frameworks, each in a different way: silently (Strands), loudly (LangGraph), and mid-recovery by provider rejection (CrewAI).

### Honest limitations

- 3 runs per cell is a trend check, not a statistical claim; a single task, a single prompt, and the same model across all runs — a different model may reason differently about tool error messages.
- At `type`, verification is impossible even for a perfect agent (no document store exists behind the id). "0/3 verified" therefore conflates "couldn't" with "didn't notice" — the traces separate them: Strands' exit-0-without-verification is the agent dropping the task's verification requirement, not merely failing at it.
- CrewAI's `type` death was a provider-side 400 during the error-recovery conversation; which layer kills the run is provider- and version-dependent.
- At `remove`, "0/3 verified" is true by construction for every framework — the meaningful number there is the exit-0 rate (silent failure), not the verified rate.

## Observability design

A local recorder proxy sits in front of every framework:

- `proxy/rec_proxy.py` — an HTTP server listening on :8118, forwarding to any OpenAI-compatible endpoint (`LLM_API_KEY` + `LLM_BASE_URL`) and writing every call to `traces/llm_calls_<framework>[__<run_label>].jsonl`. Records the full request (messages, tool schemas, system prompt), the raw response (SSE-streamed or JSON), token usage, latency, and HTTP status. The API key is stripped before writing.
- An `X-Run-Label` header splits traces per run; clients that don't send custom headers get their framework inferred from the `<fw>__` label prefix.
- Strands/LangChain stream SSE; `proxy/parse_sse.py` reassembles the stream into the same shape as non-streamed responses (content / reasoning / tool_calls / usage).
- `runs/run_matrix.py` drives all 27 runs in ~270s and `runs/analyze_matrix.py` aggregates them into `artifacts/matrix_report.json` with schema-aware wrong-arg detection.

Same shape across frameworks is what makes the comparison honest — a single proxy in front of everyone produces directly diffable logs.

## Honest limitations

- 3 runs per cell is a trend check, not a statistical claim; standard guidance treats ~30 runs as the floor for median estimation.
- A single task (one tool + one verification) is exactly where model-driven frameworks shine. LangGraph's graph structure pays off in complex branching / human-approval / parallel workflows that we did not test.
- Results are model-dependent. A different model will change reasoning volume, tool-call tendencies, and output variance.
- Dependency footprints and versions move fast; numbers here are from the initial install snapshot.

## Repo layout

```
frameworks/   one implementation per framework (Strands / LangGraph / CrewAI)
common/       the two shared deterministic tools
proxy/        recorder proxy + SSE reassembly + first-run report
runs/         matrix drivers (27-run base + 9-run complex) and aggregation
traces/       recorded LLM traffic (one file per run) - the primary data
outputs/      per-run result JSON written by each framework
artifacts/    NOT tracked: analysis outputs, rebuild with runs/*.py
              (analyze_tax, analyze_scaling, correct_findings, analyze_matrix)
```

## License

MIT
