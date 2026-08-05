# UEL — Unified Engineering Language

> HW is SW and SW is HW

UEL is a **content-addressed, typed graph of engineering claims** — components
exchanging conserved quantities across ports, analyses justifying design decisions,
and assumption envelopes continuously calibrated by test data — authored and
consumed primarily by AI engineering agents, and compiled outward into the
artifacts (geometry, BOMs, travelers, status views) through which a design is born
into the physical world.

**Status: v0.2 — the compiler sees inside the physics.** Everything v0.1 proved
(parser → units → conservation → envelopes → content hashing → staleness →
scheduler → DFM → calibration → projections), plus the three features the v0.1
retrospective demanded: **level quantities as types** (`22 dBW`, `dB/K`, dBHz
derived not asserted — ADR-0006), **expression cores** (formulas in the
language, dimension-checked before anything runs, interval uncertainty —
ADR-0005), and **targets + seam values** (acceptance computed against the lock
on every build; fences checked against the values actually flowing —
ADR-0007).

## The two documents

- [`docs/spec.md`](docs/spec.md) — **what UEL is** (language design, Draft 0.1)
- [`docs/program.md`](docs/program.md) — **how it gets built** (program plan, Draft 0.1)

Everything else in this repository is downstream of those two.

## Sixty seconds of UEL

```text
requirement LNK-002 {
  eirp_dbw = 22 dBW ± cal                   # a LEVEL: dB re W is the type
  min_margin_db = 3 dB
}

analysis LinkMargin {
  intent req.LNK-002 "does the link close at max range?"
  framing { envelope { g_over_t_dbk in [20, 40 dB/K] } }   # checked against the
  knowns {                                                 # value that FLOWS
    eirp_dbw <- req.LNK-002.eirp_dbw        # references, never copies
    freq <- req.MIS-001.carrier_freq
    max_range <- req.LNK-002.max_range
    data_rate <- req.MIS-001.data_rate
    required_ebn0_db <- req.LNK-002.required_ebn0_db
    g_over_t_dbk <- GtAnalysis.outputs.g_over_t_dbk
  }
  core expr {                               # the formula IS language now
    let lambda = const.c0 / freq
    let fspl_db = 2 * db(4 * const.pi * max_range / lambda)
    cn0_dbhz = eirp_dbw - fspl_db + g_over_t_dbk - db(const.k_B)
    margin_db = cn0_dbhz - db(data_rate) - required_ebn0_db
  }
  outputs {
    cn0_dbhz : dBHz ±                       # dBHz DERIVED by the checker:
    margin_db : dB ± target >= req.LNK-002.min_margin_db   # acceptance computed
  }
  judgment accepted "5.38 dB, T02-validated 5.1 ± 0.3" doubts "EIRP moves it 1:1"
}
```

- The **physics is the type checker** — now inside the formula too: units are a
  free-abelian-group checker with log-referenced *levels* as first-class types;
  `dBW − dB + dB/K − db(J/K)` type-checks to `dBHz`, and forgetting `db()`
  around a data rate is a compile error naming both types, not a wrong margin.
- The **fence is the type**: downstream assumptions must sit inside upstream
  guarantees — compared against the *locked value actually flowing* across the
  seam, with the producer cited. Targets make requirement satisfaction a
  computed verdict: violated = red gate; met-on-the-nominal-but-band-crosses =
  a standing warning handed to the reviewer.
- **Change is computed, not remembered**: content hashes quantize to declared
  tolerances in SI, so `850 mm` → `0.85 m` is not a change, `52 dBm` → `22 dBW`
  is not a change, sub-tolerance noise is not a change, and a requirement bump
  invalidates exactly its cone. An expr core's canonical text is its identity.
- **Reality writes back**: measurements land as overlays with provenance and
  history; bands tighten; discrepancies open investigations; consumers flip
  stale through the same hash machinery. Uncertainty from expr cores is a
  computed worst-case enclosure, not an asserted number.

## Quickstart

```sh
git clone <this repo> && cd unified-engineering-language
python3 -m uel check examples/apache-one     # compile-time pipeline (no deps, stdlib only)
python3 -m uel build examples/apache-one     # run stale analysis cores
python3 -m uel stale examples/apache-one     # what does the current state invalidate?
python3 -m uel project all examples/apache-one   # BOM/ICD/travelers/status, hash-stamped
python3 -m uel calibrate examples/apache-one/test/W12_static.json examples/apache-one
python3 -m uel query provenance spar_v8.panel_mass_per_span examples/apache-one
python3 -m uel graph examples/apache-one --dot | dot -Tsvg > graph.svg
python3 examples/apache-one/leverage.py      # the R2 instrumentation, measured live
```

`pip install -e .` gives you `uel` on PATH; nothing else is required — the kernel
is deliberately zero-dependency (ADR-0002).

## Layout

| Path | Contents |
|---|---|
| `uel/` | The reference implementation (Python, stdlib only) |
| `uel/stdlib/` | Shipped libraries, written in UEL: domain table, claim taxonomy, materials, DFM rulesets |
| `conformance/` | The suite all work is graded against — incl. the R1 de-risk pair set (11/11) and the mechanical fix-loop driver |
| `tests/` | Implementation unit tests (50-node staleness demo, core-protocol contracts, calibration loop, red-team pins) |
| `examples/apache-one/` | The vertical slice: cross-coupled, built, calibrated, leverage-measured |
| `examples/ground-station/` | An IMAP I-ALiRT X-band ground station, designed by an agent org: architect contract → three parallel engineering agents → adversarial review → calibration |
| `examples/ground-station-lc/` | The same capability at 1/10 the cost: coherent COTS array + steptrack software + ballast site — a trade-study excursion run in the graph |
| `docs/` | Constitution, frozen schema, syntax reference, core protocol, decision log, boot library |
| `.github/workflows/ci.yml` | The merge gate |

## Grading

```sh
python3 -m unittest discover -s tests    # 50 tests
python3 -m conformance.runner            # 60 cases: schema/parse/units/fmt/fixloop/check/derisk
```

Both run in CI on every push; the checker gates the scheduler; nothing merges on
trust (program §2.2).

## What v0.2 deliberately does not do

LSP, FMU transport, surrogates, remote execution, SysML bridges, distributor
refresh, sensitivity-aware staleness, expression conditionals, per-instance
graph state, statistical (non-enclosure) uncertainty — all named for v0.3+ in
spec §11 and the ADRs.
The open problems are held honestly in spec §10; current status per problem is
tracked in [`docs/boot/architecture.md`](docs/boot/architecture.md).

## License

MIT.
