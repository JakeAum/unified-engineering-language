"""The compile-time pipeline (spec §4.4): every check that runs on every diff,
in seconds, with no solver. Stages land phase by phase:

  Phase 2: parse, resolve, units/dimensions (inside the resolver)
  Phase 3: content hashing, staleness vs. lock
  Phase 4: port/conservation, budget rollups, envelope contracts, DFM, geometry
  Phase 5: (projections read the checked graph; nothing extra here)

`run_checks` assumes resolution already ran (it receives the Resolution) and adds
the later-phase stages as they exist. Compile time gates runtime: the scheduler
refuses to run cores while this pipeline reports errors.
"""

from __future__ import annotations

from .diagnostics import Bag
from .resolver import Resolution


def run_checks(res: Resolution, bag: Bag, lock: bool = True) -> None:
    from . import conservation, envelopes

    conservation.check(res, bag)
    envelopes.check(res, bag)
    if lock:
        from . import staleness

        staleness.report(res, bag)
