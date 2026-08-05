# UEL — Unified Engineering Language

> HW is SW and SW is HW

UEL is a **content-addressed, typed graph of engineering claims** — components
exchanging conserved quantities across ports, analyses justifying design decisions,
and assumption envelopes continuously calibrated by test data — authored and
consumed primarily by AI engineering agents, and compiled outward into the
artifacts (geometry, BOMs, travelers, status views) through which a design is born
into the physical world.

**Status: v0.1.3 — the kernel proof (spec §11), the economics scheduler, and a
kernel that audits itself.** Parser → units → conservation → envelopes →
content hashing → staleness → scheduler → DFM → calibration → projections, all
behind a conformance suite, all demonstrated on a physically coherent vertical
slice. On top of the staleness oracle: attention ranking (`stale --rank`),
information value of candidate measurements (`query info-value`), and the
standing work queue (`agenda`) a continuously running agent org wakes to
(ADR-0005). Around all of it: `uel init` puts the whole thing in any repository
with its agent harness (ADR-0006), and `uel doctor` grades both your model's
drift and the kernel's own honesty, writing the latter up as an upstream issue
(ADR-0007).

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
- **Compiled reports prove they weren't touched**: every projection carries a
  digest of its own body, so `uel doctor` separates a *doctored* traveler
  (hand-edited after compilation, still claiming its graph hash) from a merely
  *stale* one — and writes up the kernel's own failures as an upstream issue,
  redacted for a public tracker.

## Use it on your own project

```sh
pip install "uel @ git+https://github.com/JakeAum/unified-engineering-language"
cd your-repo && uel init .            # or: uel init hardware/
uel check . && uel build . && uel agenda .
```

`uel init` scaffolds two layers: the **project** (manifest with hash
tolerances, a starter model that checks clean and builds, a core on the JSON
protocol, a measurement-campaign template) and the **agent harness** —
`AGENTS.md` boot context, the `uel-loop` skill, a SessionStart hook that prints
the agenda into a waking session, a PostToolUse hook that runs `uel check` on
every `.uel` edit and hands the diagnostics straight back, a CI merge gate, and
the standing loop protocol with its cost log. Existing files are never
clobbered; `.claude/settings.json` is merged, not replaced; every harness file
is a silent no-op if the kernel isn't installed. `--harness none` writes the
project alone (ADR-0006).

## Quickstart on this repository

```sh
git clone <this repo> && cd unified-engineering-language
python3 -m uel check examples/apache-one     # compile-time pipeline (no deps, stdlib only)
python3 -m uel build examples/apache-one     # run stale analysis cores
python3 -m uel stale examples/apache-one     # what does the current state invalidate?
python3 -m uel stale examples/apache-one --rank  # ...and where should attention go first?
python3 -m uel agenda examples/apache-one    # the standing work queue (ADR-0005)
python3 -m uel query info-value examples/apache-one  # which measurement buys the most?
python3 -m uel project all examples/apache-one   # BOM/ICD/travelers/status, hash-stamped
python3 -m uel calibrate examples/apache-one/test/W12_static.json examples/apache-one
python3 -m uel query provenance spar_v8.panel_mass_per_span examples/apache-one
python3 -m uel doctor examples/apache-one     # drift, debt, and kernel defects
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
| `uel/templates/` | What `uel init` writes into an adopting repository: starter project + agent harness |
| `conformance/` | The suite all work is graded against — incl. the R1 de-risk pair set (11/11) and the mechanical fix-loop driver |
| `tests/` | Implementation unit tests (50-node staleness demo, core-protocol contracts, calibration loop, red-team pins) |
| `examples/apache-one/` | The vertical slice: cross-coupled, built, calibrated, leverage-measured |
| `docs/` | Constitution, frozen schema, syntax reference, core protocol, decision log, boot library |
| `.github/workflows/ci.yml` | The merge gate |

## Grading

```sh
python3 -m unittest discover -s tests    # 90 tests
python3 -m conformance.runner            # 54 cases: schema/parse/units/fmt/fixloop/check/derisk/agenda
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
