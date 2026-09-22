"""Inspect the checkpoint file left behind by the entry-node crash (probe q1)."""
import json
from pathlib import Path

f = next(Path("/tmp/ckpt_probe_q1").rglob("*.json"))
r = json.load(open(f))
print("checkpoint file:", f.name)
print("keys:", sorted(r.keys()))
cp = None
try:
    import base64
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
    from langgraph.checkpoint.base import BaseCheckpointSaver

    saver = BaseCheckpointSaver()
    cp = saver.serde.loads_typed((r["cp_type"], base64.b64decode(r["cp_blob"])))
except Exception as e:
    print("decode failed:", e)
if cp:
    print("checkpoint source:", cp.get("source"))
    print("checkpoint ts:", cp.get("ts"))
    print("channel_versions keys:", list((cp.get("channel_versions") or {}).keys()))
    print("channel_values:", list((cp.get("channel_values") or {}).keys()))
