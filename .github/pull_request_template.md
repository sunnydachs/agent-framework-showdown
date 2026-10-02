## What this changes

<!-- 1-2 sentences: what changed and why. A new experiment, a fixed measurement, a
     corrected ledger figure — say which. -->

## Evidence

<!-- Every number this PR publishes must be recomputable from committed traces.
     Paste the command you ran and its output. -->

- [ ] `python3 runs/analyze_<experiment>.py` reproduces the figures this PR states
- [ ] New traces and outputs are committed (they are the evidence, not a cache)
- [ ] `artifacts/` was NOT committed (it is regenerated, and gitignored)
- [ ] If a ledger in `articles/` changed, `python3 scripts/check_ledgers.py` passes
- [ ] Incomplete or failed runs are reported as such, not folded into a rate
