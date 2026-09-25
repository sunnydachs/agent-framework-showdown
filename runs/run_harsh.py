"""Runs the schema-change harshness ladder (Experiment 5, H):

3 frameworks x 4 harsh levels x 3 runs = 36 runs.

Levels (what changed in the word_count schema, prompts stay FIXED):
  rename : word_count(content: str)      — arg renamed (drift baseline)
  type   : word_count(content: int)      — arg TYPE changed to a doc id
  remove : word_count()                  — the text arg DELETED entirely
  add    : word_count(content, note: str)— NEW REQUIRED arg never in prompts

Run labels: <framework>__harsh_<level>_run<N> — the recorder proxy splits
traces per run via the X-Run-Label header. Appends to runs/manifest_harsh.jsonl.

Run: python runs/run_harsh.py [--levels rename type remove add] [--runs 3]
"""
import argparse
import json
import os
import subprocess
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
LEVELS = ["rename", "type", "remove", "add"]
RUNS_PER = 3
TIMEOUT_S = 240  # error recovery can add a few calls; drift baseline ran ~4-8s

MANIFEST = ROOT / "runs" / "manifest_harsh.jsonl"


def model_from_env():
    model = os.environ.get("MODEL", "")
    if not model:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("MODEL="):
                    model = line.strip().split("=", 1)[1].strip()
                    break
    if not model:
        raise SystemExit("MODEL not found in env or .env")
    return model


def proxy_alive():
    from urllib.request import urlopen

    try:
        with urlopen("http://127.0.0.1:8118/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def run_one(framework, level, run_idx):
    fw = FRAMEWORKS[framework]
    label = f"{framework}__harsh_{level}_run{run_idx}"
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "SCENARIO": "base",
        "TOOL_VARIANT": "harsh",
        "HARSH_LEVEL": level,
        "MODEL": model_from_env(),
        "HOME": str(ROOT),
    }
    env.update(fw["env"])
    t0 = time.time()
    try:
        r = subprocess.run(
            [str(ROOT / fw["py"]), fw["script"]],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=TIMEOUT_S,
        )
        ok = r.returncode == 0
        out = (r.stdout or "")[-600:]
        err = (r.stderr or "")[-600:] if not ok else ""
    except subprocess.TimeoutExpired as e:
        ok = False
        out = (e.stdout or b"").decode()[-600:] if e.stdout else ""
        err = f"timeout after {TIMEOUT_S}s"
    elapsed = time.time() - t0
    rec = {"label": label, "framework": framework, "harsh_level": level, "run": run_idx,
           "ok": ok, "elapsed_s": round(elapsed, 1), "stdout_tail": out, "stderr_tail": err}
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {label}  {elapsed:.1f}s", flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", nargs="*", default=LEVELS)
    ap.add_argument("--runs", type=int, default=RUNS_PER)
    args = ap.parse_args()
    levels = [l for l in args.levels if l in LEVELS]

    if not proxy_alive():
        raise SystemExit("rec proxy not healthy on http://127.0.0.1:8118/health — do NOT start a second instance; ask the orchestrator")

    total = len(FRAMEWORKS) * len(levels) * args.runs
    print(f"harsh ladder: {len(FRAMEWORKS)} frameworks x {len(levels)} levels x {args.runs} runs = {total}")
    print(f"manifest -> {MANIFEST}")
    t0 = time.time()
    n_ok = 0
    for level in levels:
        for framework in FRAMEWORKS:
            for run_idx in range(1, args.runs + 1):
                rec = run_one(framework, level, run_idx)
                n_ok += 1 if rec["ok"] else 0
                time.sleep(2)
    print(f"\nDONE: {n_ok}/{total} exited 0 in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
