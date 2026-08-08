# Trade study — Python units libraries vs. the hand-rolled engine

*Question posed 2026-08-08. Evaluates whether UEL should adopt an existing Python
units library in place of `uel/units.py` (418 lines, zero dependencies).*

## 0. The question is two questions

They have different answers, and conflating them is the main way this decision
gets made wrong:

- **A — the language.** Does the *checker* adopt a units library? This is
  compile-time: dimensional inference over expression ASTs, envelope
  containment, budget rollups, and the SI normalization that content hashes are
  computed from. No values need exist.
- **B — the computation modules.** Do *cores* use one? This is runtime, in a
  separate process, on concrete numbers.

A is a question about the kernel's identity function. B is a question about
developer convenience for people writing analysis scripts. Answering them
together would either bloat the kernel or impoverish the cores.

## 1. Candidates

Facts verified from PyPI and upstream `pyproject.toml`, 2026-08-08.

| Library | Version | Python | License | Runtime dependencies |
|---|---|---|---|---|
| **Pint** | 0.25.3 | ≥3.11 (main: ≥3.12) | BSD | `flexcache`, `flexparser`, `platformdirs`, `typing-extensions` |
| **unyt** | 3.1.0 | ≥3.10 | BSD-3 | `numpy`, `sympy`, `packaging` |
| **astropy.units** | 8.0.1 | ≥3.11 | BSD-3 | `numpy≥2.0`, `pyerfa`, `PyYAML`, `packaging`, `astropy-iers-data` |
| **forallpeople** | 2.7.1 | — | — | **none** |
| **Unum** | 4.2.1 | `>=2.4,<4` | **GPL** | **none** |
| **sympy.physics.units** | — | — | BSD | `sympy` → `mpmath` |
| *status quo* — `uel/units.py` | 0.6.0 | ≥3.11 | — | **none** (418 lines) |

Note Pint's floor is *rising*: released 0.25.3 still matches our 3.11, but main
has moved to 3.12. Adopting it would couple our supported-Python range to
theirs.

Unum's `requires_python` of `>=2.4,<4` is Python-2-era metadata, and its release
history is six releases across thirteen years — 2009, 2010, 2013, 2013, 2018,
and 4.2.1 in January 2022. Production-stable is a fair label; actively developed
is not.

## 1a. Licensing — a gate, not a criterion

**Unum is GPL. UEL is MIT.** This is checked before anything technical, because
it is not a trade-off that a strong technical score could outweigh.

Importing a GPL library into the kernel and distributing the result makes the
combined work subject to GPL terms on the standard copyleft reading. MIT → GPL
is a one-way door: we can relicense our own code, but no downstream consumer can
un-GPL the combination. And it lands precisely where it hurts most — UEL's whole
position is a tool that slots into anyone's stack, and its intended adopters are
commercial engineering organizations, many of which have procurement policies
that exclude GPL from shipped products. A GPL kernel would be an adoption
barrier aimed exactly at the users the project exists to serve.

*(Not legal advice; the effect is clear enough to gate on and a real adoption
decision should be confirmed by counsel.)*

**The gate binds the kernel, not the cores.** A core is a separate process
invoked over a JSON pipe. Arm's-length IPC is the textbook case for *not*
creating a derivative work, so a core author using a GPL library is their own
compliance question and not UEL's. Unum is therefore disqualified for §5 and
merely unattractive for §6.

Every other candidate is BSD or MIT-compatible and clears the gate.

## 2. Criteria

Not generic criteria — the things `uel/units.py` is actually load-bearing for,
each traceable to a line of the kernel.

| # | Criterion | Why it is a requirement here | Weight |
|---|---|---|---|
| C1 | **Byte-stable canonical SI normalization** | Content hashes are computed over tolerance-quantized SI (`uel/hashing.py`). The unit table is part of the identity function. | **Decisive** |
| C2 | **Zero runtime dependencies** | ADR-0002. The kernel must run anywhere Python runs, including inside a core's sandbox. | **Decisive** |
| C3 | **Valueless dimensional inference** | `uel/expr.py` infers dimensions over an AST at check time. Nothing has a value yet. | High |
| C4 | **Error recovery with spans and fixes** | Diagnostics are the product surface: all errors at once, each with a code, a span, a `reason`, and often a verbatim fix. Not an exception on the first bad op. | High |
| C5 | **Currency as a base dimension** | Cost is a flowing quantity of the one graph (spec §7.3). `USD` is base dimension 8. | High |
| C6 | **Composed level references** | ADR-0006: `dBW/(K*Hz)` and `dB/K` are how link budgets and G/T are actually written. | High |
| C7 | **Strict affine discipline** | `degC/W` is a hard error (UEL0303), not a convenience to be auto-converted. | Medium |
| C8 | **Unit vocabulary breadth** | Fewer "unknown unit" diagnostics for authors. | Medium |

## 3. The matrix

✅ meets · ◐ partial · ❌ fails

| | Pint | unyt | astropy.units | forallpeople | Unum | sympy.units | **hand-rolled** |
|---|---|---|---|---|---|---|---|
| **License gate** | ✅ BSD | ✅ BSD | ✅ BSD | ✅ | ❌ **GPL** | ✅ BSD | ✅ MIT |
| C1 stable identity | ❌ | ❌ | ❌ | ◐ | ❌ | ❌ | ✅ |
| C2 zero deps | ❌ (4) | ❌ (numpy+sympy) | ❌ (5, incl. a dated IERS data pkg) | ✅ | ✅ | ❌ | ✅ |
| C3 valueless inference | ❌ | ❌ | ❌ | ❌ | ❌ | ◐ | ✅ |
| C4 recovery + spans + fixes | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| C5 currency dimension | ✅ | ◐ | ◐ | ❌ (fixed 7 SI) | ◐ (as a derived unit) | ◐ | ✅ |
| C6 composed dB refs | ❌ (Beta; "compound not comprehensive") | ❌ | ✅ (`DecibelUnit`; pycraf precedent) | ❌ | ❌ | ❌ | ✅ |
| C7 affine strictness | ◐ (permissive by flag) | ◐ | ◐ | ❌ | ❌ | ◐ | ✅ |
| C8 vocabulary breadth | ✅ (best in field) | ✅ | ✅ | ◐ | ◐ | ✅ | ◐ (curated) |
| C9 actively maintained | ✅ | ✅ | ✅ | ◐ | ❌ (6 releases / 13 yrs) | ✅ | ✅ |

**C9 was added when Unum surfaced it.** Liveness is not a nice-to-have for
something inside an identity function. A dormant dependency cannot ship the fix
when a conversion factor turns out wrong, and correcting it downstream by
monkey-patching would be the C1 failure in its purest form — our hashes
diverging from what the library says they are.

## 4. The decisive criterion is C1, and it is structural

Everything else is a trade. C1 is a contradiction.

UEL's central promise is that **change is computed, not remembered**: a node's
identity is a hash over its inputs, quantized to declared tolerances in SI. The
unit table is therefore not a utility the kernel *calls* — it is part of the
function that *defines identity*. Whoever owns the conversion factors owns the
hashes.

Hand that to a third party and there are exactly two options, both bad:

1. **Put the library's version in `tool_pins()`.** Today that returns
   `{python, uel, edition}`, and every entry flows into every recipe hash. Add
   Pint and any patch release — including one that adjusts a conversion factor's
   last ULP, or reorders a registry — restales every node in every lock in every
   repository. Reproducibility now depends on someone else's release cadence.
2. **Leave it out of the pins.** Then two machines with different Pint versions
   compute different SI values, agree that a lock is fresh, and are wrong. A lock
   claiming freshness it does not have is worse than a stale one, because
   nothing ever tells you.

Pint's own documentation confirms there is no escape hatch: *"Pint does not
provide a built-in 'freeze' mechanism for registries."* Registries are
assembled at import from definition files, and programmatic additions are
explicitly not persistent. That is a reasonable design for a calculation
library and disqualifying for an identity function.

The same argument applies to unyt and astropy with more force, since their unit
tables track upstream scientific data (astropy literally ships a dated IERS data
package as a runtime dependency).

**A content-addressed system must own its unit table as versioned data it
changes deliberately.** That is not a preference; it is the same reason the lock
file is committed.

## 5. Recommendation A — the language: build, don't buy

**Keep `uel/units.py`. Do not adopt.**

The scoreboard is 8/8 for 418 lines against a best case of 4/8 plus a dependency.
But the reason is not the score, it is that the two failures that matter (C1,
C2) are structural rather than fixable, and the next two (C3, C4) would each
require an adapter layer comparable in size to the engine being replaced —
wrapping a library that raises on the first bad operation into something that
reports every error with a span and a machine-applicable fix is most of the work
of just doing the inference.

And the capabilities UEL leans on hardest are precisely where the field is
weakest. Currency as a base dimension is unusual; composed decibel references
are rarer still. Pint's logarithmic support is explicitly Beta and its own docs
advise converting log quantities to base units "as quickly as possible" — the
opposite of what a link budget wants, where the whole calculation lives in dB
and `dBW/(K*Hz)` is a type you carry, not a step you pass through.

## 6. Recommendation B — the cores: buy freely, but never across the boundary

Opposite answer, because the constraints invert. A core is a separate process
already outside ADR-0002's fence, invoked over the JSON protocol, receiving
concrete numbers. A library there costs the kernel nothing.

| Core workload | Recommendation |
|---|---|
| Array/field numerics (FEA, CFD, meshes) | **unyt** — numpy-native, benchmarks fastest, least arithmetic overhead |
| General engineering breadth | **Pint** — widest vocabulary, best conversion coverage |
| RF, spectrum, link budgets | **astropy.units** (+ `pycraf`, built for spectrum management) |
| Structural, SI-only, no deps wanted | **forallpeople** |
| Closed-form arithmetic | **none needed** — see below |

**Unum is not recommended even here**, where its GPL is no longer a blocker. It
is zero-dependency and works with numpy arrays without depending on numpy, which
is a genuinely nice property — but it is effectively dormant, and every job it
could do is done better by a maintained alternative. Zero dependencies is a
virtue for the kernel, which is not where it is allowed to run.

Two rules:

1. **A library `Quantity` must never cross the JSON boundary.** The protocol is
   `{value, unit, si}` and stays that way. The `si` field exists precisely so a
   core needs no unit library at all — `spar_static.py` reads `v["si"]` and does
   float arithmetic. Serializing a Pint object would smuggle a dependency into
   the graph's identity, which is §4 all over again.
2. **Determinism still binds.** A core using a library inherits that library's
   version into its own reproducibility story. Pin it in the core's declared
   wrapper (`tool "pint" "0.25.3"`), which already hashes into the recipe.

The elegant case: **`core expr` cores need none of these.** The kernel evaluates
the formula itself, with its own units engine and interval arithmetic. The
transparent rung of the fidelity ladder is also the dependency-free one — which
is a real argument for pushing more cores down onto it.

## 7. What to steal anyway

Rejecting the dependency is not rejecting the work:

- **Pint's unit vocabulary, as data.** C8 is our weakest column. Import
  definitions into `uel/units.py`'s table under *our* hash and *our* review —
  the definitions are facts about the world, not code we need to depend on.
- **astropy's logarithmic unit model** is the most mature in the field and worth
  reading as a critique of ADR-0006 before edition 2027 freezes it.
- **Pint's `autoconvert_offset_to_baseunit` flag** is evidence that affine
  strictness is a genuine fork in the road, not an oversight. Pint chose
  convenience with an opt-in; we chose UEL0303. Both are defensible; ours is
  right for a system whose job is to refuse.

## 8. What would reverse this

Kill criteria, so the decision stays falsifiable:

0. **A candidate relicenses permissively.** The gate in §1a is the only
   rejection here that is about paperwork rather than engineering. If Unum ever
   ships under MIT/BSD it re-enters the study — though it would still need to
   clear C1, C9, and the capability columns, which is a tall order.
1. **Array-valued quantities enter the kernel.** If the graph ever carries
   fields rather than scalars, unyt's numpy integration stops being a
   convenience and starts being the design. Revisit immediately.
2. **Vocabulary becomes the top diagnostic.** If UEL0301 ("unknown unit") is
   what authors hit most, C8 outweighs C1 and the answer is to import
   definitions faster — still as data, not as a dependency.
3. **A library ships a frozen, versioned, content-addressable registry** with a
   stability guarantee. That single change would flip C1, and C1 is the whole
   argument.

## Sources

- [Pint — logarithmic units](https://pint.readthedocs.io/en/stable/user/log_units.html)
- [Pint — defining units and dimensions](https://pint.readthedocs.io/en/stable/advanced/defining.html)
- [unyt: Handle, manipulate, and convert data with units in Python (JOSS 2018)](https://arxiv.org/abs/1806.02417)
- [unyt — comparison to Pint / quantities](https://github.com/yt-project/unyt/issues/17)
- [astropy — magnitudes and other logarithmic units](https://docs.astropy.org/en/stable/units/logarithmic_units.html)
- [astropy — DecibelUnit](https://docs.astropy.org/en/stable/api/astropy.units.DecibelUnit.html)
- [pycraf — conversions (spectrum management)](https://bwinkel.github.io/pycraf/conversions/index.html)
- [forallpeople](https://github.com/connorferster/forallpeople)
- [Unum on PyPI](https://pypi.org/project/Unum/) · [Unum documentation](https://unum.readthedocs.io/)
- [physipy — alternative packages survey](https://physipy.readthedocs.io/en/mkdocs_playground/misc/alternative-packages/alternative-home.html)
- [Physical-type correctness in scientific Python (arXiv 1807.07643)](https://arxiv.org/pdf/1807.07643)
