"""Inspect Cell A pilot evidence: trace calls, 8764 errors, persist probe."""
import json

for lbl in ["langgraph__crash_durable_run1", "langgraph__crash_mem_run1"]:
    f = f"traces/llm_calls_langgraph__langgraph__{lbl}.jsonl".replace("langgraph__langgraph__langgraph__", "langgraph__langgraph__")
    lines = [json.loads(l) for l in open(f) if l.strip()]
    print(lbl, "-> trace calls:", len(lines))
    for l in lines:
        print("    elapsed:", l.get("elapsed_s"), "status:", l.get("status"))

print()
d = json.load(open("outputs/langgraph_crash_langgraph__crash_8764_run1__8764.json"))
print("8764:", json.dumps(d, indent=1))

print()
p = json.load(open("outputs/crewai_crash_crewai__crash_persist_probe__persist.json"))
print("persist_probe:", json.dumps(p, indent=1, default=str)[:700])
