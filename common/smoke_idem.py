"""Smoke test for the idempotency layer (Experiment 4, pre-runner check)."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools_idem import IdempotencyLedger, publish_with_key, publish_hash_key, CallerBugError

DB = "/tmp/idem_smoke.sqlite"
Path(DB).unlink(missing_ok=True)

led = IdempotencyLedger(DB)

# 1. new key executes
r1 = publish_with_key("Article A", "k1", led)
assert r1["deduped"] is False and r1["result"]["status"] == "published", r1

# 2. same key + same params -> deduped, no re-exec
r2 = publish_with_key("Article A", "k1", led)
assert r2["deduped"] is True and r2["result"] == r1["result"], r2

# 3. same key + different params -> CallerBugError
try:
    publish_with_key("Article A v2", "k1", led)
    raise SystemExit("FAIL: expected CallerBugError")
except CallerBugError:
    pass

# 4. concurrency: 8 threads same key -> exactly 1 execution
results = []
lock = threading.Lock()


def worker():
    r = publish_with_key("Concurrent article", "k2", led)
    with lock:
        results.append(r)


ts = [threading.Thread(target=worker) for _ in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
execs = sum(1 for r in results if r["deduped"] is False)
assert execs == 1, f"FAIL: {execs} executions"
assert len(results) == 8

# 5. hash-key: identical article -> deduped
h1 = publish_hash_key("Same bytes article", led)
h2 = publish_hash_key("Same bytes article", led)
assert h1["deduped"] is False and h2["deduped"] is True

# 6. hash-key: reworded article -> executes again (the false negative)
h3 = publish_hash_key("Same bytes article (reworded)", led)
assert h3["deduped"] is False

print(f"SMOKE OK: k2 executions={execs}/8, ledger rows={len(led.rows())}")
