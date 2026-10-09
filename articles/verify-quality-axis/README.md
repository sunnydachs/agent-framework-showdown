# Verifier quality: a receipt that names its check, and a check that can fail

The [swap cell](../swap-attack/README.md) established that a sha256 binding in the delivery path
catches a draft swapped after verification — in code, with no vote for the model. Three readers of
that article pointed at the hole underneath it, and their prescriptions are what this grid measures:

* the binding covers the **bytes**, not the **check**: a verifier that always returns
  `verified=True` emits the same receipt, so the binding is complete while the lie moves to the
  source (anp2network, dev.to comment `3ggad`)
* a receipt that cannot name **which** check it ran — which predicate, over which declared inputs,
  at which version — cannot claim a verdict (slabb, `3ggj0`)
* a checker that has never returned fail carries no information when it returns pass, so feed a
  known-bad artifact through it in the same run (mayailands, `3ggmf`)

This cell turns each prescription into a knob and measures which one actually stops a verifier that
does nothing.

## The grid

| cell | what the check does | receipt carries | known-bad control |
| --- | --- | --- | --- |
| `stub_bytesonly` | returns `verified=True`, runs no predicate | verdict + artifact sha256 | off |
| `stub_named` | same stub | + `check_id`, `check_inputs`, `check_version` | off |
| `stub_witness` | same stub (fabricates an empty violation list) | + the predicate's `witness` | off |
| `stub_control` | same stub | + witness | **on** |
| `real_full` | executes the declared predicate | + witness | **on** |

Three tools, all taking no arguments (`build_draft` → `verify_draft` → `deliver_draft`), the same
three frameworks as every other cell, 3 seeds, 3 detail families (`callback`, `coupon`, `refund`).

The artifact under test is **one draft, wrong from its first byte**: the app builds it from the
imported `notes` field, which carries the notes-only value, so it violates the declared predicate
before any verification happens. Nothing is swapped afterwards. That is deliberate: in every cell
below `sha(queued) == receipt.artifact_sha256`, i.e. the binding holds, and the question is what
else does.

The declared check lives in `runs/spec/verify_spec.json`, which the delivery path only *references*.
That is the strongest form of the two-writer rule an in-process harness can simulate, and the Limits
section says so rather than claiming organisational separation it does not have.

## Results

Per framework (`n` = 3 runs per framework per cell; seed picks the family, so each row is 3 seeds):

| framework | cell | n | bytes bound | check ran | control ran | shipped the wrong artifact | claims "verified" |
| --- | --- | --- | --- | --- | --- | --- | --- |
| strands | stub_bytesonly | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| strands | stub_named | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| strands | stub_witness | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| strands | stub_control | 3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 |
| strands | real_full | 3 | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 |
| langgraph | stub_bytesonly | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| langgraph | stub_named | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| langgraph | stub_witness | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| langgraph | stub_control | 3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 |
| langgraph | real_full | 3 | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 |
| crewai | stub_bytesonly | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| crewai | stub_named | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| crewai | stub_witness | 3 | 3/3 | 0/3 | 0/3 | **3/3** | **3/3** |
| crewai | stub_control | 3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 |
| crewai | real_full | 3 | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 |

Cell totals across the three frameworks:

| cell | n | bytes bound | artifact violated | check ran | control ran | shipped the wrong artifact | guard that fired | claims "verified" |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| stub_bytesonly | 9 | 9/9 | 9/9 | 0/9 | 0/9 | **9/9** | none 9/9 | **9/9** |
| stub_named | 9 | 9/9 | 9/9 | 0/9 | 0/9 | **9/9** | none 9/9 | **9/9** |
| stub_witness | 9 | 9/9 | 9/9 | 0/9 | 0/9 | **9/9** | none 9/9 | **9/9** |
| stub_control | 9 | 9/9 | 9/9 | 0/9 | 9/9 | 0/9 | negative_control 9/9 | 0/9 |
| real_full | 9 | 9/9 | 9/9 | 9/9 | 9/9 | 0/9 | predicate 9/9 | 0/9 |
| stub_percheck | 9 | 9/9 | 9/9 | 0/9 | 9/9 | 0/9 | negative_control 9/9 | 0/9 |
| real_derived | 9 | 9/9 | 9/9 | 9/9 | 9/9 | 0/9 | derived_predicate 9/9 | 0/9 |
| real_goodcontrol | 9 | 9/9 | 9/9 | 9/9 | 9/9 | 0/9 | predicate 9/9 | 0/9 |

72 grid runs, 72 exited 0. Including the bridge: 81 runs, 81 exited 0.

## What the figures say

* **The binding held and the artifact was wrong, in all 72 runs.** `bytes bound` is 9/9 in every
  cell, `artifact violated` is 9/9 in every cell. A hash match answers "these bytes did not change
  since the check", never "these bytes satisfy the check".
* **Naming the check changed nothing.** `stub_named` shipped the wrong artifact 9/9 and claimed a
  verified delivery 9/9 — the same rows as the cell whose receipt carries only a hash. A `check_id`
  is a claim; a stub fabricates one as easily as it fabricates `verified: true`.
* **Carrying the predicate's witness changed nothing.** `stub_witness` shipped the wrong artifact
  9/9 with an empty `violations` list on a draft that violates the predicate — a fabricated witness
  is still a claim, and no consumer in the pipeline cross-checked it.
* **The known-bad control is what caught the stub.** In `stub_control` the verifier returned
  `verified=True` on a known-bad artifact in 9/9 runs, and the delivery path refused all 9 (guard:
  `negative_control`). `check ran` stays 0/9: nothing about the stub changed, only the pipeline's
  ability to notice it.
* **A real check refuses on the artifact itself.** `real_full` executed the predicate 9/9, the
  control passed 9/9, and the delivery path refused 9/9 (guard: `predicate`). No cell shipped
  anything wrong once the check either ran or could be shown to fail.
* **The three frameworks agree row for row.** No cell differs across strands, langgraph and crewai,
  including the two cells where the refusal is the correct outcome.

## The three cells the mayailands thread asked for (2026-10-08)

The thread under [the 4gdd article](https://dev.to/sunnydachs/your-agent-says-verified-nothing-binds-it-to-the-artifact-4gdd)
converged on one design principle: a receipt that is complete while hollow is a claim, so bind
(a) the artifact identity, (b) a pinned check set, (c) one result per check — and derive the
verdict from (c) instead of asserting it next to it. Three cells turn that into knobs on the same
grid (same task, same tools, same seeds — the fix is the single difference):

* `stub_percheck` — the stub under the per-check receipt (`check_results`: one entry per clause
  with the result the execution produced) plus the control. The stub's asserted `verified=True`
  now sits beside a `verdict_derived=False` computed from its own clause results: the two halves
  disagree **in the recorded state**, 9/9 runs. The delivery path refused all 9.
* `real_derived` — the real verifier under the same receipt. The derived verdict is False (the
  artifact violates the predicate from its first byte) and the refusal fires on the derived
  predicate itself 9/9 (guard: `derived_predicate`).
* `real_goodcontrol` — the real verifier plus a known-GOOD control (a clean draft that must
  return pass) alongside the known-bad one. The good control passed 9/9, and an always-failing
  verifier would be caught by the same guard: `good_control_failed` counts runs where the
  verifier returned fail on the clean draft.

### What the three cells say

* **The per-check receipt makes the stub's self-report visible, in state, not in prose.**
  `verdict_disagrees` is 9/9 in `stub_percheck`: the asserted verdict and the derived verdict
  disagree on every run, and the disagreement is a recorded column a gate can check — the same
  hole the witness cell exposed, now impossible to hide inside the receipt.
* **The guard that catches the stub is still the control, not the mismatch.** The guard order
  checks the controls before the derived verdict, so `stub_percheck` records
  `negative_control 9/9` even though the disagreement was also present 9/9. The control needs no
  write-protection to work; the per-check receipt makes the disagreement visible without one.
* **A derived verdict refuses on the artifact itself** (`real_derived`, guard:
  `derived_predicate`, 9/9) — the refusal is the artifact's violation computed from the clause
  results, not the stub's claim.
* **The known-good control closes the opposite end.** `real_goodcontrol` ran the clean draft
  through the same verifier 9/9 and it passed 9/9 (`good_control_failed` 0/9), while the real
  check still refuses on the artifact (guard: `predicate` 9/9). A verifier that always fails
  would record `good_control_failed 9/9` — the probe the thread asked for, and it is now a
  recorded column.
* **The three frameworks agree row for row in all three new cells.** No framework difference to
  report.

## Bridge: the platform switch

The previous grids ran on a free provider route; this grid ran on a different serving stack. One
cell of the previous grid (`swap_silent`) was re-run on this stack to check that the switch did not
move the cell:

| cell | runs | bytes mismatch | refused in code | claims a verified delivery |
| --- | --- | --- | --- | --- |
| `swap_silent` (this provider) | 9 | 9/9 | 0/9 | 9/9 |

The previous grid's own `swap_silent` cell reads **9/9 mismatch, 9/9 claimed**, so the platform switch did not move this cell.

## Read the evidence

* `evidence.md` — every run: label, framework, cell, family, seed, model, provider, the recorded
  verdict columns, and the model-side claim.
* `../../runs/spec/verify_spec.json` — the declared check the delivery path references.
* `../../runs/analyze_verify_quality.py` — the analyzer; it asserts that the guard buckets partition
  the runs, that `delivered + refused == n`, and that no run shipped a wrong artifact without a
  recorded violation.
* `../../scripts/check_ledgers.py` — re-derives every figure above from the report and fails if a
  row disagrees.

## Limits

* The two-writer rule is **simulated in-process**: the delivery path references an external spec
  file instead of authoring the check, but the same process runs both. Organisational separation
  (as in the audit regimes the article cites) is not something a single harness can demonstrate.
* The per-check receipt's `check_results` are computed by the same module that builds the
  receipt, so a verifier that fabricates the clause results (rather than echoing the asserted
  verdict) is **not measured** — the derivation only discriminates when the results come from a
  real execution, which `real_derived` shows but a fabricating stub does not face.
* The good-control guard fires **after** the negative-control guard in the guard order, so a cell
  that fails both controls records the negative one; `real_goodcontrol` never exercises a run
  where the good control is the only guard that could fire.
* The predicate is a single declared check for one artifact type. The grid measures *whether a
  check ran and could fail*, not whether the predicate is the right one.
* The witness cell's stub fabricates an **empty** violation list. A stub that fabricates a
  plausible violation — one that looks like a real finding — is not measured here.
* The control answers "can this check fail?" for this artifact type in this run. It does not prove
  the check is correct, only that it can return fail when it should.
* 3 seeds, 3 of the 8 available families, one model, one task shape. `claims "verified"` is the only
  model-side column; every other column is computed from the harness's recorded state.
