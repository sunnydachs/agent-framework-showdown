"""Smoke driver for the counting experiment: one run per framework x mode.

Env: SMOKE_FW=strands|langgraph|crewai, SMOKE_MODE=ids|stats
Run: SMOKE_FW=langgraph SMOKE_MODE=stats .venv-<fw>/bin/python common/smoke_counting.py
"""
import os
import runpy

FW = os.environ.get("SMOKE_FW", "langgraph")
MODE = os.environ.get("SMOKE_MODE", "ids")

os.environ.update({
    "OPENAI_BASE_URL": "http://127.0.0.1:8118/v1",
    "RUN_LABEL": f"smoke_counting_{FW}_{MODE}",
    "SCENARIO": "counting",
    "COUNT_MODE": MODE,
    "COUNT_SIZE": "11",
    "COUNT_SEED": "1",
    "COUNT_LO": "9",
    "COUNT_HI": "",
    "QUESTION": "How many ids are there with id >= 9?",
})
if FW in ("langgraph", "crewai"):
    os.environ["OPENAI_API_KEY"] = "dummy-key"
if FW == "crewai":
    os.environ["CREWAI_TELEMETRY"] = "false"
    os.environ["OTEL_SDK_DISABLED"] = "true"

os.environ["MODEL"] = ""
for line in open(".env"):
    if line.strip().startswith("MODEL="):
        os.environ["MODEL"] = line.strip().split("=", 1)[1].strip()

runpy.run_path(f"frameworks/{FW}_counting.py", run_name="__main__")
