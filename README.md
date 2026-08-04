# UEL — Unified Engineering Language

> HW is SW and SW is HW

UEL is a **content-addressed, typed graph of engineering claims** — components
exchanging conserved quantities across ports, analyses justifying design decisions,
and assumption envelopes continuously calibrated by test data — authored and
consumed primarily by AI engineering agents, and compiled outward into the
artifacts (geometry, BOMs, travelers, status views) through which a design is born
into the physical world.

**Status: v0.1 — the kernel proof (spec §11), complete.** Parser → units →
conservation → envelopes → content hashing → staleness → scheduler → DFM →
calibration → projections, all behind a conformance suite, all demonstrated on a
physically coherent vertical slice.

## The two documents

- [`docs/spec.md`](docs/spec.md) — **what UEL is** (language design, Draft 0.1)
- [`docs/program.md`](docs/program.md) — **how it gets built** (program plan, Draft 0.1)

Everything else in this repository is downstream of those two.

## Sixty seconds of UEL

```text
component MainSpar : functional {
  port root_attach : mechanical.translation { force: [0, 3 kN] ± cal }
  budget mass <= 470 g ± 10 g              # rollups compute the margin
}

binding MainSpar -> spar_v8 : physical {
  process cnc_turn                          # activates that DFM ruleset
  material AL7075_T6 from lib.materials
  geometry spar_v8_geom                     # shape is code + assertions
}

analysis SparStaticLimit {
  intent req.STR-014 "carry limit root moment, FoS >= 1.5"
  framing {
    model beam.euler_bernoulli
    assume rigid_root because "root fitting stiffness >> spar"
    envelope { root_moment in [0, 260 N*m] }
  }
  knowns { root_moment <- req.STR-014.root_moment
           section_Ixx <- spar_v8.section_Ixx }   # references, never copies
  core python "analysis/spar_static.py"
  outputs { FoS : dimensionless ± }
  judgment accepted "FoS 2.04; physical" doubts "root stiffness unverified until W12"
}
```

- The **physics is the type checker**: units are a free-abelian-group checker;
  every power domain's effort×flow must be power; nets balance statically.
- The **fence is the type**: downstream assumptions must sit inside upstream
  guarantees, or the compile error tells you which physics was dropped and why
  ("you modeled this beam as rigid; flutter needs its first bending mode").
- **Change is computed, not remembered**: content hashes quantize to declared
  tolerances in SI, so `850 mm` → `0.85 m` is not a change, sub-tolerance noise
  is not a change, and a requirement bump invalidates exactly its cone.
- **Reality writes back**: measurements land as overlays with provenance and
  history; bands tighten; discrepancies open investigations; consumers flip
  stale through the same hash machinery.

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
| `docs/` | Constitution, frozen schema, syntax reference, core protocol, decision log, boot library |
| `.github/workflows/ci.yml` | The merge gate |

## Grading

```sh
python3 -m unittest discover -s tests    # 41 tests
python3 -m conformance.runner            # 52 cases: schema/parse/units/fmt/fixloop/check/derisk
```

Both run in CI on every push; the checker gates the scheduler; nothing merges on
trust (program §2.2).

## What v0.1 deliberately does not do

LSP, FMU transport, surrogates, remote execution, SysML bridges, distributor
refresh, sensitivity-aware staleness — all named for v0.2/v0.3 in spec §11.
The open problems are held honestly in spec §10; current status per problem is
tracked in [`docs/boot/architecture.md`](docs/boot/architecture.md).

## License

MIT.
