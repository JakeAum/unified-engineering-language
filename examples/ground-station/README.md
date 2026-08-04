# ground-station — an X-band station for IMAP I-ALiRT, designed by an agent org

A 5 m X-band ground station receiving the **IMAP** (Interstellar Mapping and
Acceleration Probe, Sun–Earth L1) **I-ALiRT real-time space-weather broadcast**
at 8447.5 MHz / 2 kbps from up to 1.65 million km — modeled end to end in UEL,
and built the way the program plan says organizations should build (program §2,
§9): **an architect's contract, parallel engineering agents, a decorrelated
adversarial review, and a calibration campaign** — with the merge gate deciding
what exists at every step.

## How it was built (the org experiment)

1. **Architect** (one context) authored `model/requirements.uel`, the complete
   functional skeleton `model/station.uel` (every component, port, and net),
   and [`INTERFACES.md`](INTERFACES.md) — node names, output units, envelope
   fences, and file ownership, fixed up front. Executable **stubs** carry the
   contract's nominal values (spec §9.2: architecture as a contract agents fill in).
2. **Three engineering agents in parallel** — RF/link, structures/servo,
   facilities — each owning disjoint files, each self-verifying on an isolated
   copy of skeleton + other-team stubs. The seams are deliberately
   cross-coupled: RF consumes structures' pointing loss and facilities' LNA
   temperature; structures consumes RF's beamwidth; facilities consumes
   structures' servo power.
3. **Adversarial reviewer** (no shared authoring context, instructed to refute)
   recomputed every locked number, probed cores with perturbed inputs, and
   filed findings — see [`REVIEW.md`](REVIEW.md). Verdict: ship with fixes;
   all five applied, ripples verified.
4. **Calibration campaign** (`test/`): T01 bench + solar Y-factor tightened the
   LNA noise band and validated G/T; T02 first light validated the link margin
   against the IMAP track itself.

### What the discipline caught (the point of the exercise)

- **The structures agent refused a bad architect nominal.** The contract said
  the pedestal mode lands at 4–6 Hz; correct physics with the contract's own
  stiffness gives **24.7 Hz**. The agent kept the physics, recorded the
  disproof in its judgment, and showed the "compliant" alternative would bust
  the pointing requirement. The contract now carries the erratum.
- **The facilities agent refused a bad physics hint** (passive shade/vent
  cannot hold an enclosure below ambient with internal dissipation) and
  declared a TEC mitigation with provenance instead of fudging the number.
- **The reviewer caught the architect's seam-direction error** — the contract
  prescribed unsound containment for a flowing value — plus a servo sized to
  mean wind instead of gusts (60 % torque understatement), a copied literal
  that would have drifted staleness-invisibly, stub-era judgment prose, and a
  tautological assertion. All fixed; the ripple went exactly where the hash
  graph said it would.

## The design, as it stands

| Question | Answer (from `uel.lock`, post-calibration) |
|---|---|
| Does the link close? | **margin 5.38 dB** against 3 dB required (C/N0 43.9 dB-Hz, Eb/N0 10.9 dB at 2 kbps) — validated at first light ✅ |
| Station figure of merit | **G/T 29.59 dB/K** at 10° elevation (gain 50.65 dBi, T_sys 119.0 K after T01 tightened the LNA band to 41 ± 2 K) |
| Can it point? | 0.039° RSS against 0.05° required (0.074 dB pointing loss), servo bandwidth 8.2 Hz under a 24.7 Hz structure, drives sized to the 30 kN·m 3 s gust |
| Does it survive? | 45.6 kN·m stowed survival moment sizes the foundation; every fence from −30 to 45 °C site range checked |
| Does it power? | Peak 5.27 kW against the 8 kW feed (margin after 20 % growth policy); UPS ride-through 76 min against 10 required |
| What does it cost? | **$224.8k against the $260k cap**; critical path 20 weeks (pedestal) against 26; mass 3295 kg of 4500 budgeted |

## Drive it

```sh
python3 -m uel check examples/ground-station      # the whole design, checked in seconds
python3 -m uel stale examples/ground-station
python3 -m uel project all examples/ground-station # BOM / ICD / travelers / status
python3 -m uel query provenance lna_x40k.noise_temperature examples/ground-station
python3 -m uel graph examples/ground-station --dot | dot -Tsvg > station.svg
```

Things to try: bump `data_rate` to `8000 Hz` in `model/requirements.uel` and
watch exactly `LinkMargin` go stale and the margin fall ~6 dB; set `eirp_dbw`
to `16 dB` and the envelope fence rejects it at compile time before any core
runs; break a DFM feature in `geom/counterweight_bracket.py` and the
`cnc_3axis` ruleset answers with the machinist's reason.

*Mission-parameter caveat: I-ALiRT RF specifics (EIRP, exact rate/coding) are
design anchors marked `± cal` with draft-ICD provenance, load-bearing by
reference — an ICD update ripples through every consuming analysis
mechanically, which is the language working as designed.*
