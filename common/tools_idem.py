"""Idempotency layer for the destructive publish tool (Experiment 4).

The enterprise pattern: a destructive action carries an idempotency key so a
retry (timeout, crash, client re-send) cannot execute it twice. The ledger is
SQLite with a UNIQUE constraint on (tool_name, idempotency_key):

  publish_with_key(article, key)
    1. look the key up in the ledger
    2. execute publish() if and only if the key is new
    3. record the result (IN THAT ORDER)

Same key + same parameter_hash  -> return the recorded result, NO re-execution.
Same key + different param_hash -> reject: caller bug (key collision).
Concurrency: the first writer INSERTs a PENDING row; concurrent callers lose
the insert (IntegrityError), then WAIT on the row and return its result.

Also ships the BROKEN variant: publish_hash_key(article) derives the key from
sha256(article) ONLY - no position in the conversation. This is what happens
when an LLM retry reasons again and emits a NEW tool call with reworded
arguments: the content-hash key misses the dedup and the action re-executes.

Run: from common/tools_idem.py (used by runs/run_crash_idem.py).
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from tools_hitl import publish

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = Path(os.environ.get("IDEM_LEDGER_PATH", str(ROOT / "idem_ledger.sqlite")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency (
    key            TEXT NOT NULL,
    tool_name      TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('PENDING','SUCCESS','FAILED')),
    result_json    TEXT,
    parameter_hash TEXT,
    created_at     REAL NOT NULL,
    UNIQUE (tool_name, key)
);
CREATE INDEX IF NOT EXISTS idx_idem_key ON idempotency (tool_name, key, status);
"""


class CallerBugError(RuntimeError):
    """Same idempotency key used for different parameters - reject."""


def parameter_hash(params: dict) -> str:
    """Stable hash of the parameters as sent (canonical JSON, sorted keys)."""
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class IdempotencyLedger:
    """SQLite ledger: (tool_name, key) unique; PENDING -> SUCCESS/FAILED.

    A crash mid-execution leaves the PENDING row in place: the key stays
    locked (no re-execution - the safe default for a destructive action) and
    later callers with that key time out; the recovery is a NEW key.
    """

    def __init__(self, path: Path = LEDGER_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: concurrent callers share ONE sqlite file and
        # every call must serialize on the lock below (WAL + busy_timeout keep
        # the file itself safe across processes).
        self.conn = sqlite3.connect(
            str(self.path), timeout=30, isolation_level=None, check_same_thread=False
        )
        self._lock = threading.Lock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(_SCHEMA)

    # -- lookup ------------------------------------------------------------
    def get(self, tool_name: str, key: str):
        with self._lock:
            row = self.conn.execute(
                "SELECT status, result_json, parameter_hash FROM idempotency "
                "WHERE tool_name = ? AND key = ?",
                (tool_name, key),
            ).fetchone()
        if row is None:
            return None
        status, result_json, phash = row
        return {
            "status": status,
            "result": json.loads(result_json) if result_json else None,
            "parameter_hash": phash,
        }

    # -- claim (the concurrency gate) ---------------------------------------
    def claim_pending(self, tool_name: str, key: str, phash: str) -> bool:
        """Try to INSERT a PENDING row. True = this caller owns the execution."""
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO idempotency (key, tool_name, status, result_json, parameter_hash, created_at) "
                    "VALUES (?, ?, 'PENDING', NULL, ?, ?)",
                    (key, tool_name, phash, time.time()),
                )
                return True
            except sqlite3.IntegrityError:
                # Row already exists: either the same params (a retry - wait) or
                # a different param_hash (caller bug - reject at the caller).
                return False

    def wait(self, tool_name: str, key: str, timeout_s: float = 60.0):
        """The insert that loses waits/reads until the owner records a result."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            row = self.get(tool_name, key)
            if row and row["status"] != "PENDING":
                return row
            time.sleep(0.05)
        raise TimeoutError(f"idempotency wait: {tool_name}/{key} still PENDING after {timeout_s}s")

    # -- record -------------------------------------------------------------
    def record_success(self, tool_name: str, key: str, result: dict):
        with self._lock:
            self.conn.execute(
                "UPDATE idempotency SET status='SUCCESS', result_json=? WHERE tool_name=? AND key=?",
                (json.dumps(result, ensure_ascii=False), tool_name, key),
            )

    def record_failed(self, tool_name: str, key: str, error: str):
        with self._lock:
            self.conn.execute(
                "UPDATE idempotency SET status='FAILED', result_json=? WHERE tool_name=? AND key=?",
                (json.dumps({"error": error}), tool_name, key),
            )

    def rows(self):
        with self._lock:
            return self.conn.execute(
                "SELECT key, tool_name, status, result_json, parameter_hash, created_at "
                "FROM idempotency ORDER BY created_at"
            ).fetchall()

    def close(self):
        self.conn.close()


# -- the guarded tool -------------------------------------------------------
_PUBLISH = "publish_article"


def publish_with_key(article: str, key: str, ledger: IdempotencyLedger = None) -> dict:
    """publish() behind the ledger. check -> execute -> record, IN THAT ORDER.

    - new key              -> execute publish(), record SUCCESS (or FAILED)
    - same key+params      -> return the recorded result WITHOUT re-executing
    - same key,diff params -> CallerBugError (caller bug)
    - concurrent callers   -> one executes, the other waits and returns it
    """
    ledger = ledger or IdempotencyLedger()
    phash = parameter_hash({"article": article})

    existing = ledger.get(_PUBLISH, key)
    if existing is not None:
        if existing["parameter_hash"] != phash:
            raise CallerBugError(
                f"key '{key}' already used with a different parameter_hash "
                f"({existing['parameter_hash'][:12]} != {phash[:12]}) - caller bug, refusing"
            )
        if existing["status"] == "PENDING":
            # A concurrent caller owns the execution (it inserted the PENDING
            # row and is mid-publish). Wait for its result instead of
            # returning the empty PENDING row.
            row = ledger.wait(_PUBLISH, key)
            return {"deduped": True, "status": row["status"], "result": row["result"]}
        return {"deduped": True, "status": existing["status"], "result": existing["result"]}

    if ledger.claim_pending(_PUBLISH, key, phash):
        try:
            out = publish(article)  # THE destructive call - exactly once per key
        except Exception as e:  # record the failure, do not leave a stale PENDING
            ledger.record_failed(_PUBLISH, key, str(e))
            raise
        ledger.record_success(_PUBLISH, key, out)
        return {"deduped": False, "status": "SUCCESS", "result": out}

    # We lost the insert: another caller with the same key owns the execution.
    row = ledger.wait(_PUBLISH, key)
    return {"deduped": True, "status": row["status"], "result": row["result"]}


# -- the BROKEN variant -----------------------------------------------------
def publish_hash_key(article: str, ledger: IdempotencyLedger = None) -> dict:
    """publish_with_key with the key derived from sha256(article) ONLY.

    The BROKEN variant we demonstrate: the key has no position in the
    conversation. Two DIFFERENT articles that hash the same string are deduped
    (a false positive), and - the tianpan.co claim - an LLM retry that reasons
    again and re-emits the call with REWORDED arguments produces a different
    content hash, so the dedup MISSES and the action re-executes (false
    negative). Content-hash keys are only correct when arguments are
    byte-identical across retries.
    """
    key = "sha256:" + hashlib.sha256(article.encode("utf-8")).hexdigest()
    return publish_with_key(article, key, ledger)


def publish_no_key(article: str, ledger: IdempotencyLedger = None) -> dict:
    """The baseline: no idempotency key - every call executes."""
    out = publish(article)
    return {"deduped": False, "status": out["status"], "result": out}
