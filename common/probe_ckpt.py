"""Probes for the durable-checkpointer build (Cell A prerequisites)."""
import inspect

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    print("SqliteSaver IMPORT OK")
except Exception as e:
    print("SqliteSaver missing:", type(e).__name__, str(e)[:120])

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple

print("CheckpointTuple fields:", CheckpointTuple._fields)
print("put sig:", inspect.signature(BaseCheckpointSaver.put))
print("put_writes sig:", inspect.signature(BaseCheckpointSaver.put_writes))
print("get_tuple sig:", inspect.signature(BaseCheckpointSaver.get_tuple))

s = BaseCheckpointSaver()
t, b = s.serde.dumps_typed({"a": 1, "b": [1, 2]})
print("dumps_typed:", t, len(b))
print("loads_typed:", s.serde.loads_typed((t, b)))
