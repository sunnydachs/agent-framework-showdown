"""CrewAI crash-resume (Experiment 4, Cell A comparison).

CrewAI HAS a persistence mechanism (@persist on Flows, SQLite-backed via
db_storage_path) - but the benchmark's crew is NOT a Flow: it is a
Crew + Task, and there is no crew-level suspension primitive that survives
process death. The approval pause here is a BLOCKING scripted-input: the
patched builtins.input prints SUSPENDED and waits for the decision file - the
"waiting for review" state. The driver SIGKILLs mid-wait; the "resume" is a
FULL re-run.

PHASE=run    : the crew runs with the scripted input BLOCKING on the decision
               file (prints SUSPENDED). The driver SIGKILLs mid-wait.
PHASE=resume : the decision file is written by the driver first; the crew
               re-runs from scratch (full re-run cost).
PHASE=persist_probe : document what @persist/db_storage_path actually store
               (a Flow-state snapshot in SQLite) vs what a crew run loses.

Run (driver): RUN_LABEL=crewai__crash_run1 PHASE=run \
     OPENAI_BASE_URL=http://127.0.0.1:8118/v1 MODEL=<model> \
     .venv-crewai/bin/python frameworks/crewai_crash_idem.py
"""
import json
import os
import sys
import time
from itertools import repeat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))

from crewai import Agent, Crew, LLM, Process, Task  # noqa: E402

PHASE = os.environ.get("PHASE", "run")
MODEL = os.environ.get("MODEL", "your-model-id-here")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8118/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "dummy-key")
RUN_LABEL = os.environ.get("RUN_LABEL", "")
APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "approve")
DECISION_FILE = Path(os.environ.get("DECISION_FILE", "/tmp/crewai_decision.json"))
WAIT_TIMEOUT_S = float(os.environ.get("WAIT_TIMEOUT_S", "600"))
T0_PROC = time.time()


def out_path(tag):
    d = ROOT / "outputs"
    d.mkdir(exist_ok=True)
    return d / f"crewai_crash_{tag}.json"


def write_out(tag, payload):
    p = out_path(tag)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"[crewai-crash] wrote {p.name}", flush=True)


def build_crew():
    llm = LLM(
        model=f"openai/{MODEL}",
        base_url=BASE_URL,
        api_key=API_KEY,
        temperature=0,
        extra_headers={"X-Run-Label": RUN_LABEL},
    )
    writer = Agent(
        role="Tech Digest Writer",
        goal="Write a ~60-word digest of the given headlines",
        backstory="You are a concise tech writer who writes flowing narratives.",
        llm=llm,
        allow_delegation=False,
    )
    write_task = Task(
        description=(
            "Write a digest of about 60 words summarizing these headlines "
            "(fetch them yourself is NOT needed - they are provided below) into a "
            "flowing narrative:\nAI agents headlines: open-source agent frameworks "
            "hit production milestone; model-driven agents quietly replace "
            "hand-coded orchestration; tool-calling reliability becomes the new "
            "benchmark; multi-agent swarms move to regulated enterprise workflows; "
            "observability standards emerge for tracing agent decisions."
        ),
        expected_output="The final digest text of about 60 words.",
        agent=writer,
        human_input=True,  # the console pause - the HITL gate
    )
    return Crew(agents=[writer], tasks=[write_task], process=Process.sequential, verbose=False)


def run_crew():
    """Script the human: input() BLOCKS on the decision file (the waiting
    state - the driver SIGKILLs here), then accepts."""
    import builtins

    def scripted_input(*a, **k):
        if PHASE == "run":
            print(f"SUSPENDED phase1_s={time.time() - T0_PROC:.2f} waiting_for=decision_file", flush=True)
            deadline = time.time() + WAIT_TIMEOUT_S
            while time.time() < deadline:
                if DECISION_FILE.exists():
                    break
                time.sleep(0.2)
            if DECISION_FILE.exists():
                d = json.loads(DECISION_FILE.read_text())
                return "" if d.get("approved", False) else "REJECTED: do not publish this."
            return ""
        # resume phase: the decision file exists - accept
        return ""

    _real_input = builtins.input
    builtins.input = scripted_input
    try:
        t0 = time.time()
        result = build_crew().kickoff()
        return result, time.time() - t0, None
    except Exception as e:
        return None, time.time() - t0, f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        builtins.input = _real_input


if PHASE == "run":
    result, elapsed, err = run_crew()
    if err is None and not DECISION_FILE.exists():
        # Killed mid-wait: normally never written. Only on a driver miss.
        write_out(f"{RUN_LABEL or 'default'}__phase1", {
            "framework": "crewai", "phase": "run", "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2), "result_tail": str(result)[:200],
        })
        print("NOT KILLED - driver never sent SIGKILL", flush=True)
    elif err is not None:
        write_out(f"{RUN_LABEL or 'default'}__phase1", {
            "framework": "crewai", "phase": "run", "run_label": RUN_LABEL,
            "elapsed_s": round(elapsed, 2), "error": err,
        })
        print("CREW ERROR before suspend", flush=True)

elif PHASE == "resume":
    # The decision file exists now (the driver wrote it). The "resume" is a
    # full re-run from scratch - no crew-level suspension survives SIGKILL.
    result, elapsed, err = run_crew()
    write_out(f"{RUN_LABEL or 'default'}__resume", {
        "framework": "crewai", "phase": "resume", "run_label": RUN_LABEL,
        "state_survived": False, "resume_s": round(elapsed, 2), "rerun": True,
        "crew_error": err, "result_tail": str(result)[:200] if result else None,
    })
    print(f"[crewai-crash] full re-run in {elapsed:.2f}s (no state to resume from)")

elif PHASE == "persist_probe":
    # Document what @persist/db_storage_path store: a Flow-state snapshot in
    # SQLite (kickoff from_checkpoint), NOT an in-flight crew-run suspension.
    info = {"framework": "crewai", "phase": "persist_probe"}
    try:
        from crewai.utilities.paths import db_storage_path

        p = Path(db_storage_path())
        info["db_storage_path"] = str(p)
        info["db_exists"] = p.exists()
        if p.exists():
            files = list(p.rglob("*.db")) + list(p.rglob("*.sqlite*"))
            info["db_files"] = [f.name for f in files][:10]
    except Exception as e:
        info["db_storage_path_error"] = str(e)[:200]
    try:
        from crewai.flow.persistence import persist
        from crewai.flow import Flow, listen, start

        @persist()
        class ProbeFlow(Flow[dict]):
            @start()
            def begin(self):
                self.state["stepped"] = True
                return "began"

            @listen("begin")
            def second(self):
                return "done"

        flow = ProbeFlow()
        out = flow.kickoff()
        info["persist_flow_kickoff"] = str(out)[:100]
        info["persist_flow_state"] = dict(flow.state)
    except Exception as e:
        info["persist_flow_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    write_out(f"{RUN_LABEL or 'default'}__persist", info)
    print(json.dumps(info, indent=1, default=str))
