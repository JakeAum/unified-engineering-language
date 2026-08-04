# Leverage record — v0.1 kernel proof on the apache-one slice

*The program's justifying claim is measured here, not asserted (program §4).
Recorded from `examples/apache-one/leverage.py`, 2026-08-04. Re-run any time;
the script measures on a scratch copy.*

| # | Scenario | Work | Wall | Reading |
|---|---|---|---|---|
| 1 | cold build (no memory) | 7/7 cores run | 249 ms | what every memoryless iteration pays |
| 2 | design change: root moment +7% | 1/7 invalidated, 6 reused | 53 ms (21% of cold) | the ripple is computed, not remembered |
| 3 | seeded defect: 400 N·m vs 260 N·m fence | UEL0501 at compile, **0 cores run** | 15 ms | the dumb half of failures costs nothing |
| 4 | calibration: W12 panel weigh-in | exact 2-node cone re-run; f₁ 13.324 → 13.121 Hz | 81 ms | reality wrote back; consumers flipped mechanically |

Supporting indicators observed on the slice (program §5.2):

- **Staleness honesty**: seeded perturbations below the declared tolerance flag
  nothing; above, exactly the reachability cone (graded continuously by
  `tests/test_staleness_50.py`).
- **Adoption depth**: all seven analyses of the slice live in the graph; zero
  side-spreadsheets exist for it.

**Honest scope.** These are substrate-mechanical numbers: invalidation
precision, reuse, and pre-solver defect capture on a slice whose cores are
reduced-order. The R2 leverage thesis — iteration N+1 of a *real*
design-build-test loop cheaper than iteration N for the org that flies the
vehicle — is instrumented by this same machinery but cannot be discharged
without the user org. It remains the program's standing empirical risk
(kill criterion §6.1).
