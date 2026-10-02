"""Shared deterministic data layer — COUNTING benchmark (Experiment A).

The ids themselves are seeded (COUNT_SEED) so every run sees the same list per
(size, seed) cell — traces stay diffable across frameworks and modes.

Tools are registered by the framework scripts (the mode split lives there):
  mode A ("model-counts"): get_id_list()  -> the id list ONLY; the model must
                             report the count itself
  mode B ("tool-counts"):  get_count_summary() -> precomputed "count", "min",
                             "max" for the question's true predicate (bounds
                             from COUNT_LO/COUNT_HI); the model answers back

Both tools take NO arguments: the precompute happens in the tool layer, so
mode B measures transcription fidelity, not the model's choice of threshold.
"""
import os
import random

COUNT_SIZE = int(os.environ.get("COUNT_SIZE", 11))
COUNT_SEED = int(os.environ.get("COUNT_SEED", 1))


def make_ids(n: int, seed: int) -> list:
    """Deterministic id list: distinct ints in [1, 400] (n=330) or [1, 50] (n<=100)."""
    rng = random.Random(seed)
    hi = 400 if n > 100 else 50
    return rng.sample(range(1, hi + 1), n)


COUNT_LO = os.environ.get("COUNT_LO", "")
COUNT_HI = os.environ.get("COUNT_HI", "")
LO = int(COUNT_LO) if COUNT_LO.strip() else None
HI = int(COUNT_HI) if COUNT_HI.strip() else None

IDS = make_ids(COUNT_SIZE, COUNT_SEED)


def true_count(ids: list, lo, hi) -> int:
    """Count of ids in [lo, hi] (None = unbounded on that side)."""
    return len([i for i in ids if (lo is None or i >= lo) and (hi is None or i <= hi)])


def fetch_ids() -> dict:
    """Return the list of numeric ids.

    Returns:
        Dict with the full id list under "ids".
    """
    return {"ids": list(IDS)}


def count_summary() -> dict:
    """Return precomputed statistics for the id list (bounds from env).

    Returns:
        Dict with "count", "min", "max" of the matching ids.
    """
    matching = [i for i in IDS if (LO is None or i >= LO) and (HI is None or i <= HI)]
    if not matching:
        return {"count": 0, "min": None, "max": None}
    return {"count": len(matching), "min": min(matching), "max": max(matching)}


TOOLS_REGISTRY = {"fetch_ids": fetch_ids, "count_summary": count_summary}
