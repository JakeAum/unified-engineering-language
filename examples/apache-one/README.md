# apache-one — the vertical slice

One brutally cross-coupled subsystem of the Apache One testbed, modeled end to end:
**aero loads → spar structure → modal → flutter** on one chain, **shaft power → bus
current → ESC heat → case temperature** on the other, joined by shared masses, an
assembly tree with mass/cost/lead-time budgets, COTS datasheets, a machined part
under a DFM ruleset, and two test campaigns whose measurements are already written
back into this directory (`calibration/`, `uel.lock`).

This is the program's proving ground (program §4 "Continuous"): every kernel
capability lands here first, and the leverage claim is measured here, not asserted.

## The graph

```
req.STR-014 ──► SparStaticLimit ◄── spar_v8_geom ◄── lib.materials.AL7075_T6
req.AER-009 ──► SparDynamic ◄────────┤    ▲ (geometry: tube OD30×1.5×1200)
        │            │               │    └ DFM: cnc_turn ruleset
        └──► WingFlutter ◄───────────┘
                  ▲  requires elastic_modes — provided by SparDynamic
req.PWR-021 ──► PowerDraw ──► EscThermal ◄── req.THM-007
                  ▲                ▲ (lumped, steady-state — declared)
battery_6s ──► esc_xr45 ──► motor_at4130     esc_mount_v3 (cnc_3axis DFM)
      (connect: voltage windows + current draws checked statically)
Vehicle ⊃ WingGroup ⊃ {MainSpar/spar_v8, rib×6, wing_skin}
        ⊃ PowerGroup ⊃ {battery, esc, motor, mount}   (mass/cost/lead rollups)
```

## Drive it

```sh
uel check examples/apache-one          # full compile-time pipeline, seconds, no solver
uel build examples/apache-one          # run stale cores in dependency order
uel stale examples/apache-one          # what does the current state invalidate?
uel project all examples/apache-one    # BOM / ICD / travelers / status, hash-stamped
uel query provenance spar_v8.panel_mass_per_span examples/apache-one
uel graph examples/apache-one --dot | dot -Tsvg > graph.svg
```

## Things to try

**Ripple a requirement.** Edit `model/requirements.uel`, bump `root_moment` to
`240 N*m`, run `uel stale` — exactly `SparStaticLimit` is invalidated (the only
consumer), with the reason named. `uel build` re-runs one core, reuses six.

**Trip an envelope.** Set `root_moment = 400 N*m`: `uel check` rejects it in
milliseconds — the load lies outside the fence `SparStaticLimit` declared for
itself (`[0, 260 N*m]`) — before any solver spends a second (UEL0501).

**Break the claim web.** In `WingFlutter`, the framing *requires*
`elastic_modes`. Point its `f1` known at a rigid analysis (or add
`assume rigid` to `SparDynamic`) and the checker answers with the spec's own
example: rigid excludes the modes flutter needs (UEL0502, both rationales cited).

**Violate shop knowledge.** In `geom/esc_mount.py`, claim
`"min_internal_radius": {"value": 1.2, "unit": "mm"}` and rebuild: the
`cnc_3axis` ruleset rejects it with the reason machinists would give you
(UEL0603).

**Let reality write back.** The two campaigns are already applied:

- `test/W12_static.json` (bench): spar mass and panel mass-per-span measured —
  bands tightened (UEL0803), deflection prediction validated ✅; the panel mass
  cone (`SparDynamic` → `WingFlutter`) re-ran mechanically: f₁ 13.324 → 13.121 Hz,
  flutter speed nearly unchanged (mass-ratio compensation — physically right).
- `test/W13_thermal.json` (flight): case temperature 84.1 °C measured against a
  predicted 81.7 ± 4 °C — consistent, recorded as ✅ validation on `req.THM-007`
  in `out/status.md`.

Provenance survives all of it: `uel query provenance` shows current value,
origin, full measurement history, and consumers.

## The leverage measurement (R2 instrumentation)

`python3 leverage.py` re-measures on a scratch copy; latest recorded run:

| Scenario | Work | Wall |
|---|---|---|
| cold build | 7/7 cores | ~250 ms |
| design change (+7% root moment) | 1 invalidated, 6 reused | ~53 ms |
| seeded defect (out-of-fence load) | caught at compile, 0 cores | ~15 ms |
| calibration (panel weigh-in) | exact 2-node cone re-run | ~81 ms |

Honest scope: this measures the **substrate's mechanical leverage** —
invalidation precision, reuse, pre-solver defect capture. The full R2 claim
(org-level design-build-test leverage) needs the user org flying the vehicle.
