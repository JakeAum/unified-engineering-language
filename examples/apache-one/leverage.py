"""Leverage instrumentation (program §4 'Continuous', spec §10.2 / R2).

Measures the *mechanical* leverage the substrate provides on this vertical
slice, on a scratch copy of the project:

  1. cold build — every core runs (the no-memory baseline every fresh context
     would otherwise pay);
  2. targeted design change — a requirements bump; how much of the graph is
     invalidated, how much is re-run, and how much is provably reusable;
  3. seeded defect — a load outside the analysis's declared fence; caught at
     compile time with zero cores run;
  4. calibration — a bench measurement lands; exactly the consuming cone
     re-runs and the answers move.

Honest scope: this is invalidation precision and pre-solver defect capture —
the substrate's contribution. The full R2 claim (org-level iteration leverage)
requires the user org flying the vehicle and stays open until then.

Usage: python3 leverage.py            (writes leverage-report.md beside itself)
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from uel.calibration import apply_overlays, ingest  # noqa: E402
from uel.checker import run_checks  # noqa: E402
from uel.diagnostics import Bag  # noqa: E402
from uel.lockfile import Lock  # noqa: E402
from uel.project import load_project  # noqa: E402
from uel.resolver import resolve_project  # noqa: E402
from uel.scheduler import build  # noqa: E402
from uel.staleness import compute  # noqa: E402


def check_and_resolve(root: Path, expect_clean: bool = True):
    bag = Bag()
    project = load_project(root, bag)
    res = resolve_project(project, bag)
    apply_overlays(res)
    run_checks(res, bag, lock=False)
    if expect_clean:
        assert bag.ok(), bag.render(project.sources_map())
    return res, bag


def timed_build(res, bag):
    t0 = time.monotonic()
    result = build(res, bag, verbose=False)
    return result, time.monotonic() - t0


def main() -> int:
    work = Path(tempfile.mkdtemp()) / "apache-one"
    shutil.copytree(HERE, work, ignore=shutil.ignore_patterns("out", "leverage-report.md", "uel.lock", "calibration"))
    rows: list[str] = []

    # -- 1. cold build ------------------------------------------------------
    res, bag = check_and_resolve(work)
    n_exec = len(compute(res, Lock.load(work / "uel.lock")).order)
    result, t_cold = timed_build(res, bag)
    assert result.ok(), result.failed
    rows.append(f"| 1. cold build | {len(result.ran)}/{n_exec} cores run | {t_cold*1000:.0f} ms | baseline every memoryless iteration pays |")
    print(f"[1] cold build: ran {len(result.ran)}/{n_exec} cores in {t_cold*1000:.0f} ms")

    # -- 2. targeted design change -----------------------------------------
    req = work / "model" / "requirements.uel"
    req.write_text(req.read_text().replace("root_moment = 225 N*m", "root_moment = 240 N*m"))
    res2, _ = check_and_resolve(work)
    rep = compute(res2, Lock.load(work / "uel.lock"))
    stale = rep.stale()
    bag2 = Bag()
    result2, t_incr = timed_build(res2, bag2)
    reused = n_exec - len(result2.ran)
    rows.append(f"| 2. design change (root moment +7%) | {len(stale)}/{n_exec} invalidated → {len(result2.ran)} re-run, {reused} reused | {t_incr*1000:.0f} ms | ripple computed, not remembered (spec §4.2) |")
    print(f"[2] design change: {stale} invalidated; re-ran {len(result2.ran)}, reused {reused}, {t_incr*1000:.0f} ms")

    # -- 3. seeded defect: load outside the declared fence ------------------
    req.write_text(req.read_text().replace("root_moment = 240 N*m", "root_moment = 400 N*m"))
    t0 = time.monotonic()
    res3, bag3 = check_and_resolve(work, expect_clean=False)
    t_check = time.monotonic() - t0
    fence = [d for d in bag3.errors if d.code == "UEL0501"]
    assert fence, "expected the envelope fence to catch the out-of-envelope load"
    rows.append(f"| 3. seeded defect (400 N*m vs 260 N*m fence) | caught at compile: {fence[0].code} | {t_check*1000:.0f} ms, 0 cores run | the dumb half of failures costs nothing |")
    print(f"[3] seeded defect caught by {fence[0].code} in {t_check*1000:.0f} ms with zero cores run")
    req.write_text(req.read_text().replace("root_moment = 400 N*m", "root_moment = 240 N*m"))

    # -- 4. calibration: bench measurement lands ----------------------------
    res4, _ = check_and_resolve(work)
    bag4 = Bag()
    payload = json.loads((work / "test" / "W12_static.json").read_text())
    summary = ingest(res4, bag4, payload, write_stubs=False)
    res5, _ = check_and_resolve(work)
    rep5 = compute(res5, Lock.load(work / "uel.lock"))
    cone = rep5.stale()
    before = {n: Lock.load(work / "uel.lock").nodes[n].outputs for n in cone}
    bag5 = Bag()
    result5, t_cal = timed_build(res5, bag5)
    lock_after = Lock.load(work / "uel.lock")
    moved = []
    for n in cone:
        for o, v in lock_after.nodes[n].outputs.items():
            prior = before.get(n, {}).get(o)
            if prior is not None and prior.value != v.value:
                moved.append(f"{n}.{o}: {prior.value} → {v.value} {v.unit}")
    rows.append(f"| 4. calibration (W12 panel weigh-in) | {summary['applied']} measured → cone {cone} re-run | {t_cal*1000:.0f} ms | reality wrote back; the next agent inherits a tighter world |")
    print(f"[4] calibration: cone {cone} re-ran in {t_cal*1000:.0f} ms; moved: {moved}")

    report = [
        "# Leverage measurement — apache-one vertical slice",
        "",
        "*Generated by `leverage.py` on a scratch copy; numbers from a real run.*",
        "",
        "| Scenario | Work | Wall | Meaning |",
        "|---|---|---|---|",
        *rows,
        "",
        f"Executable nodes in the slice: {n_exec}. "
        f"Incremental iteration cost vs cold: {t_incr/t_cold:.0%} (scenario 2), "
        f"defect capture at compile time with zero solver spend (scenario 3).",
        "",
        "**Honest scope** — this measures the substrate's mechanical leverage: "
        "invalidation precision, reuse, and pre-solver defect capture. The full "
        "R2 claim (org-level design-build-test leverage, spec §10.2) requires "
        "the user org and remains open until the vertical slice flies.",
    ]
    (HERE / "leverage-report.md").write_text("\n".join(report) + "\n")
    print(f"\nwrote {HERE / 'leverage-report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
