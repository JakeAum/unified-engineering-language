# UEL — Unified Engineering Language

> HW is SW and SW is HW

UEL is a **content-addressed, typed graph of engineering claims** — components
exchanging conserved quantities across ports, analyses justifying design decisions, and
assumption envelopes continuously calibrated by test data — authored and consumed
primarily by AI engineering agents, and compiled outward into the artifacts through
which a design is born into the physical world.

*Status: v0.1 kernel proof under construction. The constitution is ratified; the phases
land behind the merge gate in order.*

## The two documents

- [`docs/spec.md`](docs/spec.md) — **what UEL is** (language design, Draft 0.1)
- [`docs/program.md`](docs/program.md) — **how it gets built** (program plan, Draft 0.1)

Everything else in this repository is downstream of those two.

## Layout

| Path | Contents |
|---|---|
| `uel/` | The reference implementation (zero-dependency Python; ADR-0002) |
| `conformance/` | The conformance suite — the artifact all work is graded against |
| `tests/` | Implementation unit tests |
| `examples/` | The vertical slice (`apache-one`) |
| `docs/decisions/` | The decision log — architectural choices as analysis nodes |
| `docs/boot/` | The boot library — distilled context for any agent joining the work |
| `.github/workflows/ci.yml` | The merge gate |

## Quickstart

```sh
python -m uel --help          # the CLI (no install needed; or: pip install -e .)
python -m conformance.runner  # run the conformance suite
python -m unittest discover -s tests
```
