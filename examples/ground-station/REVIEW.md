# Adversarial design review — record and disposition

*Decorrelated review (program §2.2): the reviewer shared no authoring context with
the three engineering teams or the architect's integration, was instructed to
refute, recomputed every locked number independently, and probed the cores with
24 perturbed-stdin runs. Verdict as issued: **SHIP WITH FIXES (findings 1–5)**.
All five are applied; the graph is the current truth.*

## What survived attack

Every locked number reproduced to the digit (FSPL 235.332 dB, gain 50.648 dBi,
T_sys 123.0 K, G/T 29.45 dB/K, margin 5.24 ± 0.55 dB ≈ 4σ above the 3 dB floor,
loads/modes/power/UPS all confirmed). All 24 probes moved outputs exactly as
physics demands; geometry assertions genuinely fire on bad inputs. **No gamed
check found.** Both team-flagged deviations (pedestal-mode nominal, enclosure
TEC) adjudicated as honestly handled.

## Findings and disposition

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | MED | Servo sized to 10-min-mean wind moment; 3 s gust delivers ~60 % more torque | **Fixed** — WindLoads emits `gust_moment` (30.0 kN·m); ServoSizing and PointingBudget consume it; peak torque 30.2 kN·m, drive 3.5 kW; PowerBudget peak 5.27 kW, margin still positive |
| 2 | MED | Thermal-seam containment proven in the unsound direction; hot case crossed the consumer fence within 1σ; decorative `T_amb` fence | **Fixed** — SystemNoise fence widened to [−5, 40] degC (sound direction for a flowing value); fence re-targeted to the static knowns `t_amb_min`/`t_amb_max`, which the checker now evaluates |
| 3 | MED | Three RF judgments quoted stub-era numbers (optimistic by ~0.06 dB) | **Fixed** — judgment prose refreshed to integrated lock values (123.0 K / 29.45 / 5.23 / 43.7) |
| 4 | MED | One reflector assertion tautological (compared a value to itself) | **Fixed** — deleted; the falsifiable `prime_focus_above_surface` check already covers the geometry claim |
| 5 | MED | `rotating_inertia` literal copied PedestalModes' computed J — staleness-invisible drift | **Fixed** — PedestalModes outputs `inertia`; ServoSizing references it; a reflector mass change now ripples into torque sizing mechanically |
| 6 | LOW | Mixed reference-plane noise bookkeeping donates 0.18 dB of G/T (conservative direction, disclosed) | Accepted as-is; single-plane convention documented in the cores |
| 7 | LOW | Three uncertainty constants hard-coded where they could track input bands | Accepted for v0.1; recorded here — revisit if upstream bands move |
| 8 | LOW | RF-chain DC ledger duplicated across two facilities analyses | **Fixed** — hoisted to `RfChainGroup.rf_chain_dc_draw`, both analyses reference it |
| 9 | LOW | TEC electrical draw shares the `misc_draw` allocation | Accepted; allocation rationale updated in place, split deferred to detailed design |

## Post-fix state

`uel check`: clean, 102 nodes. Ripple from the fixes, all in the physically
correct direction: peak torque 18.9 → 30.2 kN·m, drive peak 2.2 → 3.5 kW,
station peak 3.96 → 5.27 kW (margin 1.67 kW after growth policy), pointing
0.036 → 0.039 deg (≤ 0.05), link margin 5.244 → 5.232 dB (≥ 3).
