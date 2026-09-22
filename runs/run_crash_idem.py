"""Runs Experiment 4: crash recovery + idempotency + audit-under-retry.

Cells (ALL LLM calls through the recorder proxy on :8118):

  A (crash-resume): 12 runs
    - langgraph durable x3 : SIGKILL mid-interrupt -> NEW process resumes from
      the durable checkpoint dir (state survives, draft NOT re-executed)
    - langgraph mem x3     : same crash with MemorySaver (the benchmark's
      current impl) - state lost, resume impossible
    - strands x3           : no suspension primitive - full re-run (dup publish)
    - crewai x3            : same - full re-run (dup publish)
    + 3x PHASE=resume8764 (no LLM): the issue-8764 shape - empty thread
      (crash before any durable checkpoint), raw resume errors recorded.
    + 1x crewai PHASE=persist_probe (no LLM): what @persist/db_storage_path
      store (flow-state snapshot) vs what a crew run loses.

  B (idempotency): 18 LLM runs - 3 modes x 2 retry shapes x 3 runs
    - position key (correct) / content-hash key (broken) / no key (baseline)
    - retry shapes: same-args re-emit vs reworded re-emit (article_delta)
    - measures: duplicate executions, distinct tool_call_ids on the wire,
      ledger dedup correctness. Per-run ledger files under traces/idem/.

  C (audit-under-retry): runs/analyze_crash_idem.py (separate step).

Run labels: strands__idem_<mode>_<shape>_run<N>, <fw>__crash_<shape>_run<N>.

Proxy lifecycle: the recorder proxy on :8118 is auto-started when no listener
answers (proxy/rec_proxy.py, stdlib only) and shut down at exit; an
already-running external proxy is left alone (its lifecycle is not ours).
Fully-recorded runs skip without any LLM call (traces + outputs append-only).
Run: python runs/run_crash_idem.py [--cell A|B|all] [--runs 3]
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IDEM_MODES = {
    "position": {"IDEM_MODE": "position"},
    "hash": {"IDEM_MODE": "hash"},
    "none": {"IDEM_MODE": "none"},
}
RETRY_SHAPES = {
    # both shapes force ONE re-emit; "same" = re-emit with the SAME arguments,
    # "reworded" = re-emit with the article_delta suffix appended (which is
    # what decides whether a content-hash key dedups)
    "same": [{}],
    "reworded": [{"article_delta": " [revised: source attribution added]", "then": None}],
}
RUNS_PER = 3
MANIFEST = ROOT / "runs" / "manifest_crash_idem.jsonl"

# retry directives: 1 forced re-emit per run; slowness that makes it realistic
IDEM_ENV_BASE = {
    "SLOW_PUBLISH_S": "2",
    "IDEM_LEDGER_PATH": "",  # filled per-run (traces/idem/<label>.sqlite)
}
CRASH_ENV_BASE = {
    "CKPT_DIR": "",  # filled per-run (traces/ckpt/<label>)
}
PROXY_PORT = 8118


def proxy_alive(port=PROXY_PORT):
    """True when something already listens on the proxy port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_proxy(port=PROXY_PORT):
    """Start proxy/rec_proxy.py when no listener is up; None when already running.

    Returns the Popen handle (or None). The caller owns shutdown ONLY for the
    proxy IT started: an external proxy is left alone.
    """
    if proxy_alive(port):
        print(f"[proxy] already listening on :{port} (external - left alone)", flush=True)
        return None
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "proxy" / "rec_proxy.py"), "--port", str(port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if proxy_alive(port):
            print(f"[proxy] started rec_proxy.py on :{port} (pid {proc.pid})", flush=True)
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"rec_proxy.py exited rc={proc.returncode} (LLM_API_KEY missing in .env?)")
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError(f"rec_proxy.py never listened on :{port} within 20s")


def shutdown_proxy(proc):
    """Stop only the proxy this driver started (None = external, leave it)."""
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    print(f"[proxy] stopped rec_proxy.py (pid {proc.pid})", flush=True)


FW_ENV = {
    "strands": {},
    "langgraph": {"OPENAI_API_KEY": "dummy-key"},
    "crewai": {"OPENAI_API_KEY": "dummy-key", "CREWAI_TELEMETRY": "false", "OTEL_SDK_DISABLED": "true"},
}


def model_from_env():
    model = os.environ.get("MODEL", "")
    if not model:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.strip().startswith("MODEL="):
                    model = line.strip().split("=", 1)[1].strip()
                    break
    return model


def base_env(label):
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "HOME": str(ROOT),
        "MODEL": model_from_env(),
    }
    return env


def log_rec(rec):
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    status = "OK  " if rec.get("ok") else "FAIL"
    print(f"[{status}] {rec['label']}  {rec.get('elapsed_s', '?')}s", flush=True)


def trace_file(label):
    # the proxy names traces llm_calls_<fw>__<label>.jsonl (fw inferred from the label prefix)
    fw = label.split("__", 1)[0] if "__" in label else "unknown"
    return ROOT / "traces" / f"llm_calls_{fw}__{label}.jsonl"


# ---------------------------------------------------------------- cell A ----
def wait_for_suspend(proc, timeout=180):
    """Read phase1 stdout until the SUSPENDED line; return (seen, phase1_s)."""
    import threading

    buf = {"lines": []}

    def reader():
        for line in proc.stdout:
            buf["lines"].append(line.strip())
            if line.startswith("SUSPENDED"):
                return

    t = threading.Thread(target=reader, daemon=True)
    t0 = time.time()
    t.start()
    t.join(timeout)
    seen = any(l.startswith("SUSPENDED") for l in buf["lines"])
    phase1_s = None
    for l in buf["lines"]:
        if l.startswith("SUSPENDED") and "phase1_s=" in l:
            try:
                phase1_s = float(l.split("phase1_s=")[1].split()[0])
            except Exception:
                pass
    return seen, phase1_s, round(time.time() - t0, 2)


def sigkill(proc):
    if proc.poll() is None:
        try:
            os.kill(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    return proc.returncode


def run_crash_fw(fw, shape, run_idx, pause_s=5.0):
    """phase1 (bg) -> SIGKILL mid-wait -> phase2 resume (fg) -> record."""
    label = f"{fw}__crash_{shape}_run{run_idx}"
    py = f".venv-{fw}/bin/python"
    script = f"frameworks/{fw}_crash_idem.py"

    # idempotent re-run: if this label is already traced, skip (traces are append-only)
    tf = trace_file(label)
    phase2_out = ROOT / "outputs" / f"{fw}_crash_{label}__resume.json"
    if tf.exists() and phase2_out.exists():
        print(f"[SKIP] {label} already recorded", flush=True)
        d = json.load(open(phase2_out))
        return {"label": label, "framework": fw, "cell": "A", "shape": shape, "run": run_idx,
                "ok": True, "skipped": True, "resume_s": d.get("resume_s"),
                "state_survived": d.get("state_survived"), "published": d.get("published")}

    env = base_env(label)
    env.update(FW_ENV[fw])
    env.update(CRASH_ENV_BASE)
    if fw == "langgraph":
        env["CKPT_DIR"] = str(ROOT / "traces" / "ckpt" / label)
        env["PHASE"] = "run"
        env["CRASH_CKPT"] = "durable" if shape == "durable" else "mem"
        env["APPROVAL_MODE"] = "approve"
    else:
        env["PHASE"] = "run"
        env["APPROVAL_MODE"] = "approve"
    if fw in ("strands", "crewai"):
        # the approval gate BLOCKS on this decision file (the waiting state);
        # the driver writes it between phase1 (SIGKILL) and phase2 (resume)
        env["DECISION_FILE"] = f"/tmp/{fw}_decision_{label}.json"
        env["WAIT_TIMEOUT_S"] = "600"
        Path(env["DECISION_FILE"]).unlink(missing_ok=True)

    t0 = time.time()
    proc = subprocess.Popen(
        [str(ROOT / py), script], cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    seen, phase1_s, waited = wait_for_suspend(proc)
    # hold mid-interrupt, then SIGKILL the process
    time.sleep(pause_s)
    rc = sigkill(proc)
    kill_ok = rc in (-9, 137) or not seen  # -9 = SIGKILL delivered; not seen = died before suspend
    suspend_s = phase1_s if phase1_s is not None else waited

    # phase2: the "new process" resumes (strands/crewai: the decision file is written first)
    if fw in ("strands", "crewai"):
        Path(f"/tmp/{fw}_decision_{label}.json").write_text(json.dumps({"approved": True}))
    env2 = dict(env)
    env2["PHASE"] = "resume"
    t1 = time.time()
    r = subprocess.run([str(ROOT / py), script], cwd=str(ROOT), env=env2, capture_output=True, text=True, timeout=300)
    resume_elapsed = time.time() - t1
    resume_ok = r.returncode == 0
    if not resume_ok:
        print(f"  phase2 stderr: {(r.stderr or '')[-300:]}", flush=True)

    # read the resume output (state survival + publish count)
    d = json.load(open(phase2_out)) if phase2_out.exists() else {}
    phase1_out = ROOT / "outputs" / f"{fw}_crash_{label}__phase1.json"
    d1 = json.load(open(phase1_out)) if phase1_out.exists() else {}
    elapsed = time.time() - t0
    rec = {"label": label, "framework": fw, "cell": "A", "shape": shape, "run": run_idx,
           "ok": bool(resume_ok and seen), "elapsed_s": round(elapsed, 1),
           "suspend_seen": seen, "suspend_s": suspend_s, "kill_rc": rc,
           "resume_s": d.get("resume_s"), "state_survived": d.get("state_survived"),
           "published": d.get("published"), "phase1_published": d1.get("published") is not None or d1.get("result_tail") is not None}
    log_rec(rec)
    return rec


def run_8764(run_idx):
    """The issue-8764 shape: empty thread (no durable checkpoint) - raw errors."""
    label = f"langgraph__crash_8764_run{run_idx}"
    out = ROOT / "outputs" / f"langgraph_crash_{label}__8764.json"
    if out.exists():
        print(f"[SKIP] {label} already recorded", flush=True)
        d = json.load(open(out))
        return {"label": label, "cell": "A", "ok": True, "skipped": True, "errors": d}
    env = base_env(label)
    env.update(FW_ENV["langgraph"])
    env["PHASE"] = "resume8764"
    t0 = time.time()
    r = subprocess.run(
        [str(ROOT / ".venv-langgraph/bin/python"), "frameworks/langgraph_crash_idem.py"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    ok = r.returncode == 0 and out.exists()
    d = json.load(open(out)) if out.exists() else {"stderr": (r.stderr or "")[-300:]}
    rec = {"label": label, "cell": "A", "ok": ok, "elapsed_s": round(time.time() - t0, 1), "errors": d}
    log_rec(rec)
    return rec


def run_persist_probe():
    label = "crewai__crash_persist_probe"
    out = ROOT / "outputs" / f"crewai_crash_{label}__persist.json"
    if out.exists():
        print(f"[SKIP] {label} already recorded", flush=True)
        return {"label": label, "cell": "A", "ok": True, "skipped": True}
    env = base_env(label)
    env.update(FW_ENV["crewai"])
    env["PHASE"] = "persist_probe"
    t0 = time.time()
    r = subprocess.run(
        [str(ROOT / ".venv-crewai/bin/python"), "frameworks/crewai_crash_idem.py"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    ok = r.returncode == 0 and out.exists()
    if not ok:
        print(f"  persist_probe stderr: {(r.stderr or '')[-300:]}", flush=True)
    rec = {"label": label, "cell": "A", "ok": ok, "elapsed_s": round(time.time() - t0, 1)}
    log_rec(rec)
    return rec


# ---------------------------------------------------------------- cell B ----
def run_idem_fw(mode, shape, run_idx):
    label = f"strands__idem_{mode}_{shape}_run{run_idx}"
    py = ".venv-strands/bin/python"
    script = "frameworks/idem_retry_tools.py"
    tf = trace_file(label)
    out = ROOT / "outputs" / f"idem_retry_{label}.json"
    if tf.exists() and out.exists():
        print(f"[SKIP] {label} already recorded", flush=True)
        d = json.load(open(out))
        return {"label": label, "framework": "strands", "cell": "B", "mode": mode, "shape": shape,
                "run": run_idx, "ok": True, "skipped": True,
                "n_execs": d.get("n_publish_execs_inproc")}

    env = base_env(label)
    env.update(FW_ENV["strands"])
    env.update(IDEM_ENV_BASE)
    env.update(IDEM_MODES[mode])
    env["RETRY_SPECS_JSON"] = json.dumps(RETRY_SHAPES[shape])
    env["IDEM_LEDGER_PATH"] = str(ROOT / "traces" / "idem" / f"idem_ledger_{label}.sqlite")
    # position mode: the caller assigns the key (same shape per run, distinct per run)
    env["IDEM_POSITION_KEY"] = f"pos:{label}"
    Path(env["IDEM_LEDGER_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        r = subprocess.run([str(ROOT / py), script], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0
        if not ok:
            print(f"  stderr: {(r.stderr or '')[-300:]}", flush=True)
    except subprocess.TimeoutExpired:
        ok = False
    elapsed = time.time() - t0
    d = json.load(open(out)) if out.exists() else {}
    rec = {"label": label, "framework": "strands", "cell": "B", "mode": mode, "shape": shape,
           "run": run_idx, "ok": ok, "elapsed_s": round(elapsed, 1),
           "n_execs": d.get("n_publish_execs_inproc"), "exec_log": d.get("exec_log")}
    log_rec(rec)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="all", choices=["A", "B", "all"])
    ap.add_argument("--runs", type=int, default=RUNS_PER)
    args = ap.parse_args()
    t0 = time.time()
    n_ok = n_total = 0
    proxy_proc = ensure_proxy()

    try:
        if args.cell in ("A", "all"):
            print("=== CELL A: crash-resume (12 runs + 4 no-LLM probes) ===", flush=True)
            for shape in ["durable", "mem"]:
                for run_idx in range(1, args.runs + 1):
                    rec = run_crash_fw("langgraph", shape, run_idx)
                    n_ok += 1 if rec["ok"] else 0
                    n_total += 1
                    time.sleep(1)
            for fw in ["strands", "crewai"]:
                for run_idx in range(1, args.runs + 1):
                    rec = run_crash_fw(fw, "noresume", run_idx)
                    n_ok += 1 if rec["ok"] else 0
                    n_total += 1
                    time.sleep(1)
            for run_idx in range(1, args.runs + 1):
                rec = run_8764(run_idx)
                n_ok += 1 if rec["ok"] else 0
                n_total += 1
            rec = run_persist_probe()
            n_ok += 1 if rec["ok"] else 0
            n_total += 1

        if args.cell in ("B", "all"):
            print("=== CELL B: idempotency (18 LLM runs) ===", flush=True)
            for mode in ["position", "hash", "none"]:
                for shape in ["same", "reworded"]:
                    for run_idx in range(1, args.runs + 1):
                        rec = run_idem_fw(mode, shape, run_idx)
                        n_ok += 1 if rec["ok"] else 0
                        n_total += 1
                        time.sleep(1)
    finally:
        shutdown_proxy(proxy_proc)

    print(f"\nDONE: {n_ok}/{n_total} ok in {time.time()-t0:.0f}s")
    return 0 if n_ok == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
