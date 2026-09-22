"""Minimal durable FileCheckpointSaver for LangGraph (Experiment 4, Cell A).

langgraph-checkpoint-sqlite is not installed in the benchmark venvs, so this
file-backed saver gives the crash-resume experiment the same durable-checkpoint
semantics (MemorySaver shape, but every checkpoint survives SIGKILL):

  put(config, checkpoint, metadata, new_versions) -> tuple config
      one JSON file per checkpoint: <dir>/<thread>/<ns>/<checkpoint_id>.json
  put_writes(config, writes, task_id)             -> writes file (pending writes)
  get_tuple(config) -> CheckpointTuple (latest for the thread, or by id)

Used by frameworks/langgraph_crash_idem.py to resume a graph in a NEW process
after the old one was SIGKILLed mid-interrupt.
"""
import base64
import json
import time
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple


class FileCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    # -- layout helpers ------------------------------------------------------
    def _thread_dir(self, thread_id: str, checkpoint_ns: str = "") -> Path:
        d = self.path / str(thread_id) / (checkpoint_ns or "root")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _cp_file(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> Path:
        return self._thread_dir(thread_id, checkpoint_ns) / f"{checkpoint_id}.json"

    # -- put -----------------------------------------------------------------
    def put(self, config, checkpoint, metadata, new_versions):
        cfg = config or {}
        thread_id = cfg.get("configurable", {}).get("thread_id", "")
        ns = cfg.get("configurable", {}).get("checkpoint_ns", "") or ""
        cp_id = checkpoint["id"]
        cp_type, cp_blob = self.serde.dumps_typed(checkpoint)
        md_type, md_blob = self.serde.dumps_typed(metadata or {})
        rec = {
            "thread_id": thread_id,
            "checkpoint_ns": ns,
            "checkpoint_id": cp_id,
            "parent": {
                "checkpoint_id": cfg.get("configurable", {}).get("checkpoint_id"),
                "checkpoint_ns": ns,
            }
            if cfg.get("configurable", {}).get("checkpoint_id")
            else None,
            "cp_type": cp_type,
            "cp_blob": base64.b64encode(cp_blob).decode("ascii"),
            "md_type": md_type,
            "md_blob": base64.b64encode(md_blob).decode("ascii"),
            "ts": time.time(),
        }
        f = self._cp_file(thread_id, ns, cp_id)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec))
        tmp.replace(f)  # atomic: a crash mid-write never corrupts the checkpoint
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": cp_id,
            }
        }

    # -- pending writes --------------------------------------------------------
    def put_writes(self, config, writes, task_id, task_path: str = ""):
        cfg = config or {}
        thread_id = cfg.get("configurable", {}).get("thread_id", "")
        ns = cfg.get("configurable", {}).get("checkpoint_ns", "") or ""
        cp_id = cfg.get("configurable", {}).get("checkpoint_id", "")
        if not cp_id:
            return
        payload = []
        for channel, value in writes:
            t, b = self.serde.dumps_typed(value)
            payload.append({"channel": channel, "type": t, "blob": base64.b64encode(b).decode("ascii")})
        f = self._thread_dir(thread_id, ns) / f"writes_{cp_id}_{task_id}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(f)
    # -- get -------------------------------------------------------------------
    def get_tuple(self, config) -> CheckpointTuple | None:
        cfg = config or {}
        thread_id = cfg.get("configurable", {}).get("thread_id", "")
        ns = cfg.get("configurable", {}).get("checkpoint_ns", "") or ""
        tdir = self._thread_dir(thread_id, ns)
        wanted_id = cfg.get("configurable", {}).get("checkpoint_id")

        if wanted_id:
            f = tdir / f"{wanted_id}.json"
            if not f.exists():
                return None
            files = [f]
        else:
            files = [p for p in tdir.glob("*.json") if not p.name.startswith("writes_")]
            files = sorted(files, key=lambda p: p.stat().st_mtime)
            if not files:
                return None
            files = [files[-1]]  # latest checkpoint for the thread

        rec = json.loads(files[0].read_text())
        checkpoint = self.serde.loads_typed((rec["cp_type"], base64.b64decode(rec["cp_blob"])))
        metadata = self.serde.loads_typed((rec["md_type"], base64.b64decode(rec["md_blob"])))

        pending_writes = []
        for wf in tdir.glob(f"writes_{rec['checkpoint_id']}_*.json"):
            # filename: writes_<checkpoint_id>_<task_id>.json -> 3-tuple form
            tid = wf.name[len("writes_") + len(rec["checkpoint_id"]) + 1:]
            for w in json.loads(wf.read_text()):
                pending_writes.append(
                    (tid, w["channel"], self.serde.loads_typed((w["type"], base64.b64decode(w["blob"]))))
                )

        parent_config = None
        if rec.get("parent") and rec["parent"].get("checkpoint_id"):
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": rec["parent"]["checkpoint_ns"],
                    "checkpoint_id": rec["parent"]["checkpoint_id"],
                }
            }
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": rec["checkpoint_ns"],
                    "checkpoint_id": rec["checkpoint_id"],
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )
