"""Runs the B-scaling matrix: 3 frameworks x complex task x 3 runs = 9 runs.

The complex task (topic comparison: 2 fetches + branch decision + digest +
verify) is the counterpart to the base digest task (27-run matrix, already done).
Together they give the scaling curve: task shape x framework.

Run labels: <framework>__complex_run<N> - the recorder proxy splits traces per
run via the X-Run-Label header.

Run: python runs/run_complex.py
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FRAMEWORKS = {
    "strands": {
        "py": ".venv-strands/bin/python",
        "script": "frameworks/strands_complex.py",
        "env": {},
    },
    "langgraph": {
        "py": ".venv-langgraph/bin/python",
        "script": "frameworks/langgraph_complex.py",
        "env": {"OPENAI_API_KEY": "dummy-key"},
    },
    "crewai": {
        "py": ".venv-crewai/bin/python",
        "script": "frameworks/crewai_complex.py",
        "env": {"OPENAI_API_KEY": "dummy-key", "CREWAI_TELEMETRY": "false", "OTEL_SDK_DISABLED": "true"},
    },
}
RUNS_PER = 3
MANIFEST = ROOT / "runs" / "manifest_complex.jsonl"


def run_one(framework, run_idx, timeout=180):
    fw = FRAMEWORKS[framework]
    label = f"{framework}__complex_run{run_idx}"
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "SCENARIO": "base",
        "TOOL_VARIANT": "base",
        "HOME": str(ROOT),
    }
    # MODEL is not baked into the scripts (provider-agnostic); pass it through.
    # Read from this process's env or the repo .env.
    import os
    model = os.environ.get("MODEL", "")
    if not model:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("MODEL="):
                    model = line.strip().split("=", 1)[1].strip()
                    break
    env["MODEL"] = model
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
    except subprocess.TimeoutExpired:
        ok = False
        out = ""
        err = f"timeout after {timeout}s"
    elapsed = time.time() - t0
    rec = {"label": label, "framework": framework, "task": "complex", "run": run_idx,
           "ok": ok, "elapsed_s": round(elapsed, 1), "stdout_tail": out, "stderr_tail": err}
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {label}  {elapsed:.1f}s", flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=RUNS_PER)
    args = ap.parse_args()
    total = len(FRAMEWORKS) * args.runs
    print(f"complex matrix: {len(FRAMEWORKS)} frameworks x {args.runs} runs = {total}")
    t0 = time.time()
    n_ok = 0
    for framework in FRAMEWORKS:
        for run_idx in range(1, args.runs + 1):
            rec = run_one(framework, run_idx)
            n_ok += 1 if rec["ok"] else 0
            time.sleep(2)
    print(f"\nDONE: {n_ok}/{total} ok in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
