"""Runs the source-boundary propagation experiment (Experiment exp-B):

3 frameworks x 3 conditions x 24 runs = 216 runs.

24 record variants per condition = 8 detail families x 3 seeds; the same 24
(family, seed) pairs repeat under each condition, only the `notes` field
changes (see common/tools_source_boundary.py).

Run labels: <framework>__source_boundary_<condition>_f<family>_s<seed> —
the recorder proxy splits traces per run via the X-Run-Label header.
Appends to runs/manifest_source_boundary.jsonl.

Run: python runs/run_source_boundary.py [--conditions clean malicious legitimate] [--runs-per 24]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))
from tools_source_boundary import FAMILY_ORDER  # noqa: E402

FRAMEWORKS = {
    "strands": {
        "py": ".venv-strands/bin/python",
        "script": "frameworks/strands_source_boundary.py",
        "env": {},
    },
    "langgraph": {
        "py": ".venv-langgraph/bin/python",
        "script": "frameworks/langgraph_source_boundary.py",
        "env": {"OPENAI_API_KEY": "dummy-key"},
    },
    "crewai": {
        "py": ".venv-crewai/bin/python",
        "script": "frameworks/crewai_source_boundary.py",
        "env": {"OPENAI_API_KEY": "dummy-key", "CREWAI_TELEMETRY": "false", "OTEL_SDK_DISABLED": "true"},
    },
}
CONDITIONS = ["clean", "malicious", "legitimate"]
SEEDS = [1, 2, 3]
RUNS_PER = 24  # = 8 families x 3 seeds
TIMEOUT_S = 300

MANIFEST = ROOT / "runs" / "manifest_source_boundary.jsonl"


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


def run_one(framework, condition, family, seed, run_idx):
    fw = FRAMEWORKS[framework]
    label = f"{framework}__source_boundary_{condition}_f{family}_s{seed}"
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "SCENARIO": "source_boundary",
        "TOOL_VARIANT": "source_boundary",
        "CONDITION": condition,
        "FAMILY": family,
        "SEED": str(seed),
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
    rec = {
        "label": label, "framework": framework, "condition": condition,
        "family": family, "seed": seed, "run": run_idx,
        "ok": ok, "elapsed_s": round(elapsed, 1), "stdout_tail": out, "stderr_tail": err,
    }
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(ROOT / "runs" / "source_boundary.log", "a") as f:
        f.write(f"{label}\n")
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {label}  {elapsed:.1f}s", flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", nargs="*", default=CONDITIONS)
    ap.add_argument("--runs-per", type=int, default=RUNS_PER)
    args = ap.parse_args()
    conditions = [c for c in args.conditions if c in CONDITIONS]
    if args.runs_per != RUNS_PER:
        raise SystemExit(f"--runs-per must stay {RUNS_PER} (8 families x 3 seeds)")

    if not proxy_alive():
        raise SystemExit(
            "rec proxy not healthy on http://127.0.0.1:8118/health — do NOT start "
            "a second instance; ask the orchestrator"
        )

    variants = [(f, s) for f in FAMILY_ORDER for s in SEEDS]
    total = len(FRAMEWORKS) * len(conditions) * len(variants)
    print(f"source boundary: {len(FRAMEWORKS)} frameworks x {len(conditions)} conditions "
          f"x {len(variants)} variants = {total}")
    print(f"manifest -> {MANIFEST}")
    t0 = time.time()
    n_ok = 0
    for condition in conditions:
        for framework in FRAMEWORKS:
            for family, seed in variants:
                rec = run_one(framework, condition, family, seed, len(variants))
                n_ok += 1 if rec["ok"] else 0
                time.sleep(2)
    print(f"\nDONE: {n_ok}/{total} exited 0 in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
