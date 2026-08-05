"""The compile-time pipeline (spec §4.4): every check that runs on every diff,
in seconds, with no solver. Compile time gates runtime."""

from __future__ import annotations

from .diagnostics import Bag
from .lockfile import Lock
from .resolver import Resolution

def run_checks(res: Resolution, bag: Bag, lock: bool = True):
    from . import conservation, contracts, dfm, envelopes, staleness

    lk = Lock.load(res.project.lock_path, bag)
    rollups = conservation.check(res, bag, lk)
    envelopes.check(res, bag)
    envelopes.check_locked(res, bag, lk)
    contracts.check(res, bag, lk)
    dfm.check(res, bag, lk)
    if lock:
        staleness.report(res, bag)
    return rollups
