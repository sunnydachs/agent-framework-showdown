"""Runs the counting-benchmark matrix (Experiment A): rows vs count.

3 frameworks x 2 modes x 68 questions = 408 runs.

Question cells (matching the Count-It benchmark's shape):
  63 = 3 list sizes (11 / 110 / 330 ids) x 7 threshold phrasings x 3 seeds
       (every (size, seed) pair gets all 7 phrasings; each phrasing lands at
       every size across seeds)
  + 5 extra size-330 probes (fresh seeds) = 68 questions total

Modes (common/tools_counting.py + the framework scripts, selected by COUNT_MODE):
  ids   (mode A, "model-counts"): the tool returns ONLY the id list; the model
        must report the count of ids matching the threshold
  stats (mode B, "tool-counts"): the tool precomputes and returns "count",
        "min", "max"; the model just answers those back

Seven threshold phrasings, each with an explicit predicate the analyzer
validates against the true id set (never a wrong count hiding a wrong filter):
  p0: "id >= 9"                    -> lo=9
  p1: "id > 9"                     -> lo=10 (strict)
  p2: "no less than 9"             -> lo=9
  p3: "below 9"                    -> hi=8
  p4: "between 5 and 9 inclusive"  -> lo=5, hi=9
  p5: "greater than 5 and less than 9" -> lo=6, hi=8 (strict both sides)
  p6: "strictly above 4"           -> lo=5

Run labels: <framework>__counting_<mode>_s<size>_p<phrasing>_r<seed>q<qidx> —
the recorder proxy splits traces per run via the X-Run-Label header.
Appends to runs/manifest_llm_counting.jsonl. Runner lines -> runs/llm_counting.log.

Run: python runs/run_llm_counting.py [--modes ids stats] [--sizes 11 110 330]
     [--seeds 1 2 3] [--limit N] [--fresh]

Resume behavior: labels already present in the manifest are skipped, so a
re-run after a crash / quota death continues where it left off (set --fresh
to re-record everything).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FRAMEWORKS = {
    "strands": {
        "py": ".venv-strands/bin/python",
        "script": "frameworks/strands_counting.py",
        "env": {},
    },
    "langgraph": {
        "py": ".venv-langgraph/bin/python",
        "script": "frameworks/langgraph_counting.py",
        "env": {"OPENAI_API_KEY": "dummy-key"},
    },
    "crewai": {
        "py": ".venv-crewai/bin/python",
        "script": "frameworks/crewai_counting.py",
        "env": {"OPENAI_API_KEY": "dummy-key", "CREWAI_TELEMETRY": "false", "OTEL_SDK_DISABLED": "true"},
    },
}
MODES = ["ids", "stats"]
SIZES = [11, 110, 330]
SEEDS = [1, 2, 3]

# Seven threshold phrasings -> explicit predicates (lo/hi; None = unbounded)
PHRASINGS = [
    {"tmpl": "How many ids are there with id >= {T}?", "lo": 9, "hi": None},
    {"tmpl": "How many ids are there with id > {T}?", "lo": 10, "hi": None},
    {"tmpl": "How many ids are there with a value no less than {T}?", "lo": 9, "hi": None},
    {"tmpl": "How many ids are there with a value below {T}?", "lo": None, "hi": 8},
    {"tmpl": "How many ids are there with a value between {T5} and {T} inclusive?", "lo": 5, "hi": 9},
    {"tmpl": "How many ids are there that are greater than {T5} and less than {T}?", "lo": 6, "hi": 8},
    {"tmpl": "How many ids are there that are strictly above {T4}?", "lo": 5, "hi": None},
]

MANIFEST = ROOT / "runs" / "manifest_llm_counting.jsonl"
LOG = ROOT / "runs" / "llm_counting.log"
TRACE_DIR = ROOT / "traces"
PROXY_PORT = 8118
TIMEOUT_S = 240


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


def proxy_alive(port=PROXY_PORT):
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def build_questions(sizes, seeds, n_extra=5):
    """The 68 questions: 63 (size x phrasing x seed) + 5 extra size-330 probes.

    Every (size, seed) pair gets all 7 phrasings (9 pairs x 7 = 63); each
    phrasing therefore lands at every size across seeds. The extra probes are
    size-330 with fresh seeds, p0 phrasing.
    """
    questions = []
    pairs = [(size, seed) for size in sizes for seed in seeds]
    for size, seed in pairs:
        for ph_i, ph in enumerate(PHRASINGS):
            text = (
                ph["tmpl"]
                .replace("{T}", "9")
                .replace("{T5}", "5")
                .replace("{T4}", "4")
            )
            questions.append({
                "qidx": len(questions) + 1, "size": size, "seed": seed,
                "phrasing": ph_i, "lo": ph["lo"], "hi": ph["hi"], "text": text,
            })
    extra_seed_base = 100
    for j in range(n_extra):
        seed = extra_seed_base + j
        ph = PHRASINGS[0]
        text = ph["tmpl"].replace("{T}", "9")
        questions.append({
            "qidx": len(questions) + 1, "size": 330, "seed": seed,
            "phrasing": 0, "lo": ph["lo"], "hi": ph["hi"], "text": text,
        })
    return questions


def run_one(framework, mode, q):
    fw = FRAMEWORKS[framework]
    label = f"{framework}__counting_{mode}_s{q['size']}_p{q['phrasing']}_r{q['seed']}q{q['qidx']}"
    trace = TRACE_DIR / f"llm_calls_{framework}__{label}.jsonl"
    if trace.exists():
        # the recorder proxy APPENDS per-label traces: reset so a re-attempt's
        # trace holds only the fresh attempt (matches the manifest's last-wins)
        trace.unlink()
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
        "RUN_LABEL": label,
        "SCENARIO": "counting",
        "COUNT_MODE": mode,
        "COUNT_SIZE": str(q["size"]),
        "COUNT_SEED": str(q["seed"]),
        "COUNT_LO": "" if q["lo"] is None else str(q["lo"]),
        "COUNT_HI": "" if q["hi"] is None else str(q["hi"]),
        "QUESTION": q["text"],
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
        "label": label, "framework": framework, "mode": mode,
        "qidx": q["qidx"], "size": q["size"], "seed": q["seed"],
        "phrasing": q["phrasing"], "lo": q["lo"], "hi": q["hi"],
        "question": q["text"],
        "ok": ok, "elapsed_s": round(elapsed, 1), "stdout_tail": out, "stderr_tail": err,
    }
    with open(MANIFEST, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(LOG, "a") as f:
        f.write(f"{label} {rec['elapsed_s']}s {'OK' if ok else 'FAIL'}\n")
    status = "OK " if ok else "FAIL"
    print(f"[{status}] {label}  {elapsed:.1f}s", flush=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="*", default=MODES)
    ap.add_argument("--sizes", nargs="*", type=int, default=SIZES)
    ap.add_argument("--seeds", nargs="*", type=int, default=SEEDS)
    ap.add_argument("--limit", type=int, default=0, help="cap the number of runs (smoke testing)")
    ap.add_argument("--fresh", action="store_true", help="re-record runs already in the manifest")
    args = ap.parse_args()
    modes = [m for m in args.modes if m in MODES]
    sizes = [s for s in args.sizes if s in SIZES]
    seeds = [s for s in args.seeds if s in SEEDS]

    if not proxy_alive():
        raise SystemExit("rec proxy not healthy on http://127.0.0.1:8118/health — do NOT start a second instance; ask the orchestrator")

    full_grid = build_questions(SIZES, SEEDS)  # the canonical 68
    questions = [q for q in full_grid if q["size"] in sizes and q["seed"] in seeds]
    if len(sizes) < len(SIZES) or len(seeds) < len(SEEDS):
        # partial schedule: drop the 5 extra probes unless the full grid is asked for
        questions = [q for q in questions if q["seed"] < 100]

    # resume: skip runs already recorded as OK (unless --fresh); FAILED runs are
    # re-attempted (a timeout / 429 death may be transient, and the analyzer
    # keeps the LAST record per label, so the fresh attempt supersedes it).
    # Torn last lines (crash mid-write) are ignored.
    done_ok = set()
    if MANIFEST.exists() and not args.fresh:
        for line in MANIFEST.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if rec.get("ok"):
                    done_ok.add(rec["label"])
            except json.JSONDecodeError:
                pass
    planned = [
        (framework, mode, q)
        for mode in modes
        for framework in FRAMEWORKS
        for q in questions
        if f"{framework}__counting_{mode}_s{q['size']}_p{q['phrasing']}_r{q['seed']}q{q['qidx']}" not in done_ok
    ]

    total = len(FRAMEWORKS) * len(modes) * len(questions)
    n_resume = total - len(planned)
    if n_resume:
        print(f"resume: {n_resume} already recorded, {len(planned)} to run")
    print(f"counting matrix: {len(FRAMEWORKS)} frameworks x {len(modes)} modes x {len(questions)} questions = {total}")
    print(f"manifest -> {MANIFEST}")
    print(f"log -> {LOG}")
    t0 = time.time()
    n_done = n_ok = 0
    stop = False
    for framework, mode, q in planned:
        if args.limit and n_done >= args.limit:
            stop = True
            break
        rec = run_one(framework, mode, q)
        n_done += 1
        n_ok += 1 if rec["ok"] else 0
        time.sleep(1)
        if not rec["ok"] and "429" in (rec.get("stderr_tail") or ""):
            print(
                "\nQUOTA: upstream 429 (free-tier daily limit) — aborting so the "
                "grid is not re-recorded as failures; resume after the daily reset"
            )
            return 2
    print(f"\nDONE: {n_ok}/{n_done} exited 0 in {time.time()-t0:.0f}s (planned {total}, resumed past {n_resume})")
    return 0 if n_done == len(planned) else 1


if __name__ == "__main__":
    sys.exit(main())
