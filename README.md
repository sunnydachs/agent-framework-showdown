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
