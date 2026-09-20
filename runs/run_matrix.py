"""Runs the full showdown matrix: 3 frameworks x 3 scenarios x 3 runs = 27 runs.

Scenarios:
  base  : 80-120 word band (the original task)
  tight : 95-105 word band (forces verify/revise loop)
  drift : tool schema renamed (word_count takes `content`), prompts still say `text`

Run labels: <framework>__<scenario>_run<N> - the recorder proxy splits traces
per run via the X-Run-Label header.

Run: python runs/run_matrix.py [--quick]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FRAMEWORKS = {
    "strands": {
        "py": ".venv-strands/bin/python",
        "script": "frameworks/strands_digest.py",
        "env": {},
    },
    "langgraph": {
        "py": ".venv-langgraph/bin/python",
        "script": "frameworks/langgraph_digest.py",
        "env": {"OPENAI_API_KEY": "dummy-key"},
    },
    "crewai": {
        "py": ".venv-crewai/bin/python",
        "script": "frameworks/crewai_digest.py",
        "env": {"OPENAI_API_KEY": "dummy-key", "CREWAI_TELEMETRY": "false", "OTEL_SDK_DISABLED": "true"},
    },
}
SCENARIOS = ["base", "tight", "drift"]
RUNS_PER = 3

MANIFEST = ROOT / "runs" / "manifest.jsonl"


def run_one(framework, scenario, run_idx, timeout=150):
    fw = FRAMEWORKS[framework]
    label = f"{framework}__{scenario}_run{run_idx}"
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "SCENARIO": scenario,
        "TOOL_VARIANT": "drift" if scenario == "drift" else "base",
        "HOME": str(ROOT),
    }
    env.update(fw["env"])
    t0 = time.time()
    try:
        r = subprocess.run(
            [str(ROOT / fw["py"]), fw["script"]],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=timeout,
        )
        ok = r.returncode == 0
        out = (r.stdout or "")[-500:]
        err = (r.stderr or "")[-500:] if not ok else ""
    except subprocess.TimeoutExpired as e:
        ok = False
        out = ""
        err = f"timeout after {timeout}s"
    elapsed = time.time() - t0
    rec = {"label": label, "framework": framework, "scenario": scenario, "run": run_idx,
           "ok": ok, "elapsed_s": round(elapsed, 1), "stdout_tail": out, "stderr_tail": err}
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {label}  {elapsed:.1f}s", flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", type=int, default=0, help="run only N scenarios for smoke testing")
    ap.add_argument("--runs", type=int, default=RUNS_PER)
    args = ap.parse_args()
    scenarios = SCENARIOS[: args.quick] if args.quick else SCENARIOS
    total = len(FRAMEWORKS) * len(scenarios) * args.runs
    print(f"matrix: {len(FRAMEWORKS)} frameworks x {len(scenarios)} scenarios x {args.runs} runs = {total}")
    t0 = time.time()
    n_ok = 0
    for scenario in scenarios:
        for framework in FRAMEWORKS:
            for run_idx in range(1, args.runs + 1):
                rec = run_one(framework, scenario, run_idx)
                n_ok += 1 if rec["ok"] else 0
                time.sleep(2)
    print(f"\nDONE: {n_ok}/{total} ok in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
