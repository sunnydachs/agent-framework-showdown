# Working agreement for this repository

Short rules for anyone — human or agent — adding an experiment to this repository.

## Ground rules

- **`traces/` is the ground truth.** Each file is one run's full exchange with the
  endpoint, recorded by `proxy/rec_proxy.py`. Every published number must be
  recomputable from these files by a script in `runs/`. If a number cannot be
  recomputed, it does not go in a ledger.
- **`artifacts/` is regenerated, not committed.** It is gitignored; run the
  analyzer to rebuild whatever you need from it.
- **No secrets in Git.** Credentials come from the environment (`LLM_API_KEY`,
  optional `LLM_BASE_URL` for any OpenAI-compatible endpoint). `.env` is
  gitignored and stays that way.
- **No absolute paths.** Scripts and docs use `$HOME` or repo-relative paths, so a
  clone runs anywhere.
- **Do not bypass the secret scan.** `git commit --no-verify` is never a fix for a
  gitleaks hit; rotate the credential and rewrite the commit.
- **Numbers live in `articles/<slug>/evidence.md`.** A README may state a result,
  but the per-cell figures and their recompute commands belong in the evidence
  file, where a reader can check them.

## Adding an experiment

1. Add the framework scripts under `frameworks/`, shared helpers under `common/`,
   and the runner + analyzer under `runs/`.
2. Reuse the existing recorder — start it once (`python3 proxy/rec_proxy.py
   --port 8118`). Never start a second instance.
3. Let one runner own the grid at a time. A re-run appends to the manifest but
   overwrites a label's trace file, so two concurrent runners can write a
   failure over a run that already succeeded.
4. Report incomplete runs as incomplete. A run that never produced an answer is
   its own column (or its own sentence); it is never folded into a success rate.
5. Commit code first, then the manifests, then the traces and outputs. Update the
   ledger in `articles/<slug>/` in the same change.

## Checks that must pass

```
python3 runs/analyze_llm_counting.py
python3 runs/analyze_source_boundary.py
python3 runs/analyze_harsh.py
python3 runs/analyze_swap_attack.py
python3 runs/analyze_verify_quality.py
python3 scripts/check_ledgers.py
```
