# Benchmarking rules these experiments follow

Working notes for experiment A (tool returns rows vs count) and B (detail provenance boundary). These are the rules the
runners and analyzers are held to, kept here so the next experiment starts from them instead of re-deriving them.

## Design

1. **Freeze the roster, run both variants back to back.** Yesterday's results are not the comparison group. Every
   condition in a matrix is recorded in the same pass, and a re-run re-records both sides.
2. **One recording proxy in front of every framework.** The proxy is the only place that sees the wire. Without it, a
   framework's own trace is a summary written by the code under test.
3. **Vary the phrasing, not just the number.** Threshold questions are asked seven ways (`>=`, `>`, `no less than`,
   `below`, a bounded range, an exclusive bounded range, `strictly above`) because a single phrasing measures the
   prompt, not the task.
4. **Seeds are part of the schedule.** A cell is a set of runs, not one run; per-cell n is printed next to every
   percentage.
5. **Report the incomplete runs as incomplete.** A run that never exited 0 is its own column, never folded into the
   failure rate and never silently dropped. In A that is 1 of 408; in B it is 0 of 216.

## Scoring

6. **Score from the recorded wire, not from the model's self-report.** Every score is recomputed from the tool
   arguments and tool results inside the trace. The model's own claim about what it did is not evidence.
7. **Recompute the ground truth too, and print the recompute.** The true count in A is re-derived from the id list in
   the recorded tool response. If the analyzer's own arithmetic were wrong, it would show up as a wrong-answer cluster
   with a suspicious shape.
8. **Never let the generator grade itself.** The framework under test does not produce the score, and no scorer reads
   a summary the framework wrote about itself.
9. **Split what a single score would hide.** In A, "wrong count" and "wrong query" are separate outcomes, so a wrong
   answer is never a filtering mistake in disguise. In B, "planted detail leaked" and "service-owned detail retained"
   are separate columns: collapsing them would hide a run that repeated both values.
10. **A confident wrong answer and a hedged wrong answer are different products.** Worth a column wherever the answer
    is a number.
11. **Uncalled tools are a finding, not an error.** Two runs in A answered correctly-shaped numbers without calling the
    tool at all; that is recorded as `n_tool_calls = 0`, not discarded as malformed.
12. **Provider defaults are not measured settings.** If a sampler default was not set explicitly, say so; do not report
    the run as a controlled-temperature run.

## Reporting

13. **Cost is a result.** Tokens per question and LLM calls per run are printed next to every accuracy figure, because a
    path that is correct at 55x the token cost is a different recommendation.
14. **Every row must add up.** `correct + wrong + incomplete == n` is asserted programmatically over the aggregate
    table rather than eyeballed.
15. **A matrix with no variance in a column is a result.** In B the framework column is flat at leakage 1.0: that
    absence of framework difference is the finding, and it decides where the fix has to live.
16. **State the control.** B's `legitimate` condition exists to rule out "the model repeats anything it has seen
    twice"; without it the malicious result has an obvious innocent explanation.

## Failure handling learned the hard way

- **Two concurrent runners corrupt the dataset.** A resume pass appends per label; an interleaved second pass can write
  a timeout over a label that already succeeded. The analyzer keeps the last record that exited 0 per label and prints
  how many labels it rescued, and only one runner is allowed at a time.
- **A daily request cap turns into fabricated failures.** When the endpoint starts answering with a rate-limit status,
  the grid records the remaining cells as errors. The runner aborts on the first such response instead of re-recording
  the grid as failures, and the schedule is resumed after the cap resets.
- **A timeout is not a wrong answer.** Size-330 runs are slow enough to hit a 240s cap; that is recorded as an
  incomplete run, and the count that was already measured successfully is not overwritten by it.
