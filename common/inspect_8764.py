"""Inspect the 8764 run trace: did the empty-thread resume re-run the graph?"""
import json

f = "traces/llm_calls_langgraph__langgraph__crash_8764_run1.jsonl"
lines = [json.loads(l) for l in open(f) if l.strip()]
print("8764 trace calls:", len(lines))
for i, l in enumerate(lines):
    req = l.get("request") or {}
    msgs = req.get("messages") or []
    print(f"  call{i}: elapsed={l.get('elapsed_s')} n_msgs={len(msgs)}")
    for m in msgs[:3]:
        c = m.get("content")
        print("     ", m.get("type"), repr(str(c)[:80]))

# also the empty dir state after the 8764 attempts
from pathlib import Path

d = Path("traces/ckpt_empty_8764")
if d.exists():
    files = sorted(d.rglob("*.json"))
    print("ckpt_empty_8764 files after attempts:", len(files))
    for x in files:
        print("   ", x.relative_to(d))
else:
    print("ckpt_empty_8764 dir missing (never created?)")
