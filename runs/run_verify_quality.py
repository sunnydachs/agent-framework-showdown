"""Runner: the verifier-quality grid (exp-B follow-up).

  python runs/run_verify_quality.py            # 3 frameworks x 5 cells x 3 seeds
  python runs/run_verify_quality.py --bridge   # re-run swap_silent on the current provider

The bridge is not part of the grid: it re-runs one cell of the PREVIOUS grid on
the provider this grid uses, so the two grids can be compared without assuming
two serving stacks behave alike. Its results land in a separate manifest.

Every run gets its own label, its own trace, and its own output file, and the
manifest is append-only with resume-by-label, so an interrupted grid continues
instead of duplicating runs.
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
from verify_quality import CELL_ORDER  # noqa: E402

FRAMEWORKS = {
    "strands": {
        "py": ".venv-strands/bin/python",
        "script": "frameworks/strands_verify_quality.py",
        "env": {"OPENAI_API_KEY": "dummy-key"},
    },
    "langgraph": {
        "py": ".venv-langgraph/bin/python",
        "script": "frameworks/langgraph_verify_quality.py",
        "env": {"OPENAI_API_KEY": "dummy-key"},
    },
    "crewai": {
        "py": ".venv-crewai/bin/python",
        "script": "frameworks/crewai_verify_quality.py",
        "env": {"OPENAI_API_KEY": "dummy-key", "CREWAI_TELEMETRY": "false",
                "OTEL_SDK_DISABLED": "true"},
    },
}
BRIDGE = {
    "strands": {"py": ".venv-strands/bin/python",
                "script": "frameworks/strands_swap_attack.py",
                "env": {"OPENAI_API_KEY": "dummy-key", "CONDITION": "swap_silent"}},
    "langgraph": {"py": ".venv-langgraph/bin/python",
                  "script": "frameworks/langgraph_swap_attack.py",
                  "env": {"OPENAI_API_KEY": "dummy-key", "CONDITION": "swap_silent"}},
    "crewai": {"py": ".venv-crewai/bin/python",
               "script": "frameworks/crewai_swap_attack.py",
               "env": {"OPENAI_API_KEY": "dummy-key", "CONDITION": "swap_silent",
                       "CREWAI_TELEMETRY": "false", "OTEL_SDK_DISABLED": "true"}},
}
SEEDS = [1, 2, 3]
FAMILIES = ["callback", "coupon", "refund"]     # family follows the seed
TIMEOUT_S = 420

MANIFEST = ROOT / "runs" / "manifest_verify_quality.jsonl"
MANIFEST_BRIDGE = ROOT / "runs" / "manifest_verify_quality_bridge.jsonl"
LOG = ROOT / "runs" / "verify_quality.log"


def model_from_env() -> str:
    model = os.environ.get("MODEL", "")
    if not model:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.strip().startswith("MODEL="):
                model = line.strip().split("=", 1)[1].strip()
                break
    if not model:
        raise SystemExit("MODEL not found in env or .env")
    return model


def proxy_upstream() -> str:
    """Which upstream the running proxy actually forwards to.

    Read from the proxy's own health endpoint, not from .env: a provider switch
    is an env override at startup, so the file on disk can name one platform
    while the process serves another. If the proxy cannot answer, the field
    says so instead of guessing.
    """
    from urllib.request import urlopen
    try:
        with urlopen("http://127.0.0.1:8118/health", timeout=5) as r:
            return json.load(r).get("upstream", "unknown")
    except Exception:
        return "unknown"


def proxy_alive() -> bool:
    from urllib.request import urlopen
    try:
        with urlopen("http://127.0.0.1:8118/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def check_model_platform():
    """Refuse to start when the model id and the serving platform disagree.

    The .env on disk can name the previous provider's model — `...:free` is an
    OpenRouter id — while the proxy forwards somewhere else. That mismatch is
    silent at launch and then fails every run, so it is caught here instead.
    """
    model, upstream = model_from_env(), proxy_upstream()
    if ":free" in model and "openrouter" not in upstream:
        raise SystemExit(
            f"MODEL={model!r} is an OpenRouter-style id, but the proxy forwards to "
            f"{upstream}. Export MODEL for this provider (NIM: "
            f"nvidia/nemotron-3-super-120b-a12b) before launching.")
    return model, upstream


def run_one(fw_name, spec, label, manifest, extra_env, run_idx):
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "SCENARIO": "verify_quality",
        "MODEL": model_from_env(),
        "HOME": str(ROOT),
    }
    env.update(spec["env"])
    env.update(extra_env)
    t0 = time.time()
    try:
        r = subprocess.run([str(ROOT / spec["py"]), spec["script"]], cwd=str(ROOT),
                           env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
        ok = r.returncode == 0
        out = (r.stdout or "")[-600:]
        err = (r.stderr or "")[-600:] if not ok else ""
    except subprocess.TimeoutExpired as e:
        ok = False
        out = (e.stdout or b"").decode()[-600:] if e.stdout else ""
        err = f"timeout after {TIMEOUT_S}s"
    elapsed = time.time() - t0
    rec = {"label": label, "framework": fw_name, "run": run_idx, "ok": ok,
           "elapsed_s": round(elapsed, 1), "model": model_from_env(),
           "provider": proxy_upstream(), "stdout_tail": out, "stderr_tail": err}
    with open(manifest, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(LOG, "a") as f:
        f.write(f"{label}\n")
    print(f"[{'OK ' if ok else 'FAIL'}] {label}  {elapsed:.1f}s", flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", action="store_true",
                    help="re-run the previous grid's swap_silent cell only")
    ap.add_argument("--cells", nargs="*", default=CELL_ORDER)
    args = ap.parse_args()

    if not proxy_alive():
        raise SystemExit("rec proxy not healthy on http://127.0.0.1:8118/health")
    model, upstream = check_model_platform()

    if args.bridge:
        manifest, table = MANIFEST_BRIDGE, BRIDGE
        todo = [(fw, spec, None, family, seed,
                 f"{fw}__verify_quality_bridge_swap_silent_f{family}_s{seed}")
                for seed, family in zip(SEEDS, FAMILIES)
                for fw, spec in table.items()]
    else:
        manifest, table = MANIFEST, FRAMEWORKS
        cells = [c for c in args.cells if c in CELL_ORDER]
        todo = [(fw, spec, cell, family, seed,
                 f"{fw}__verify_quality_{cell}_f{family}_s{seed}")
                for cell in cells
                for seed, family in zip(SEEDS, FAMILIES)
                for fw, spec in table.items()]

    done = set()
    if manifest.exists():
        done = {json.loads(l)["label"] for l in manifest.read_text().splitlines() if l.strip()}
    print(f"{'bridge' if args.bridge else 'grid'}: {len(todo)} runs "
          f"({len(done)} already done) | model={model} | {upstream}")

    t0 = time.time()
    n_ok = 0
    for fw, spec, cell, family, seed, label in todo:
        if label in done:
            continue
        # Pass the knobs explicitly, including FAMILY: the label encodes the
        # family and the seed, so the label and the run cannot drift apart.
        extra = {"SEED": str(seed), "FAMILY": family}
        if not args.bridge:
            extra["CELL"] = cell
        rec = run_one(fw, spec, label, manifest, extra, len(SEEDS))
        n_ok += 1 if rec["ok"] else 0
        time.sleep(2)
    print(f"\nDONE: {n_ok} new runs exited 0 in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
