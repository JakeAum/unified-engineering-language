# ADR-0010 — The economics scheduler: ranking attention and pricing experiments

*Status: accepted · v0.7 · 2026-08-07 · executes gap-analysis §2 moves 2 and 3 ·
extends spec §4.2 (staleness) and §8 (calibration); adds no syntax*

## Intent

The gap analysis makes an Amdahl argument against ourselves. Inside one
iteration the substrate now costs milliseconds, agent cognition costs
minutes-to-hours of context spend, and the physical oracle costs days-to-weeks.
Further substrate speedups move nothing. The two expensive terms are **agent
attention** and **oracle contact**, and the graph schedules neither:

> `uel stale` answers *what* is invalid in topological order; it should answer
> *what matters* … an agent waking up should be handed the highest-value stale
> node, not the next one in topo order.

> for each candidate measurement, expected envelope tightening times the weight
> of the consumers it feeds — even the crude form beats hand-picking campaigns.

Both are joins over data the kernel already computes. Nothing new needs to be
declared, measured, or believed; what was missing was the arithmetic and a
place to put it. *The physics is the type checker; make the economics the
scheduler.*

## Decision

A new module, `uel/economics.py`, and two commands. Both are **advice, not
authority**: the checker still gates merges, `uel build` still walks in
dependency order, and nothing here can turn a red graph green.

**1. `uel stale --rank`** value-orders the stale frontier by a weighted sum of
nine signals, each normalized to [0, 1]:

    score = Σ_t WEIGHT[t] · value_t

| term | weight | signal |
|---|---|---|
| `broken` | 10 | last run failed, or a `verify` contract the analysis declared about itself failed (ADR-0008) |
| `target` | 8 | a declared acceptance bound (ADR-0007) is violated (1.0), crosses the line inside its own band (0.4), or is pending (0.15) |
| `margin` | 6 | budget erosion (spec §7.3) of the budgets this node can actually move |
| `fence` | 5 | this analysis's own inputs against its declared envelope (spec §2.5) |
| `serves` | 4 | traces to a requirement via `intent req.*` — 1.0 sole evidence, 0.75 shared |
| `cone` | 3 | blast radius: fraction of the executable graph downstream |
| `hazard` | 2.5 | fraction of the framing model's registered hazards neither covered nor waived (UEL0510, ADR-0009) |
| `stub` | 2 | the core is a placeholder, not an analysis (UEL0807) |
| `age` | 1 | evidence age relative to the rest of the lock |

Ties break toward topological order, so equal-value work is offered in
buildable order; `frontier` separately marks nodes whose upstreams are all
fresh — actionable right now. `--all` widens the set to fresh nodes carrying
open obligations, because a violated target, an uncovered hazard and a stub are
real work that rebuilding cannot fix and the staleness oracle cannot see.

Every row ships its contributing terms — `value × weight = contribution` — and
the reported contributions sum exactly to the reported score. A rank with no
visible terms is an oracle, and this project does not ask anyone to trust one.

**2. `uel query info-value [quantity]`** prices candidate measurements:

    value = tightening × (1 + Σ consumer weight) × (1 + margin pressure)

- **tightening** — the declared ignorance a measurement removes: relative band
  width, 1.0 for `± cal` and TBD, 0 for values declared exact. Optionally
  scaled by measured elasticity (below).
- **consumer weight** — the transitive consumer cone weighted by *each
  consumer's own attention score*, normalized to the hottest node in the graph.
- **margin pressure** — the larger of the band-vs-fence pressure at a direct
  consumer and the erosion of any budget the quantity is a leaf of. It peaks
  where a measurement *decides* a verdict.

Candidates are declared quantities and port attributes, locked analysis outputs
(as validation targets), and the **unvalued leaves of a budget rollup** — which
carry no band to be uncertain about and are precisely the holes that make a
rollup indeterminate.

**3. Diagnostics UEL09xx**, raised by the economics queries only — never by
`uel check`, because being unimportant is not a compile error. `UEL0901` stale
work that scores zero (program §5.3: work with no linked failure is
presumptively dead), `UEL0902` a graph that declares no ignorance anywhere,
`UEL0903` a measurement that would settle a verdict rather than refine one.

## Why these terms, and why normalized

The ordering of the weights is a claim about engineering, and the conformance
cases pin it from both sides so that amending a weight cannot quietly invert
the intent.

- **A broken run outranks everything** because it is not a result at all. It is
  the cheapest, loudest signal in the system and it blocks its whole cone.
- **A verdict outranks a pressure.** A violated target is finished work that
  failed; an eroded budget is work that is going badly. Finished-and-wrong is
  worth more attention than in-progress-and-tight, which is why `target` sits
  above `margin` and `fence`.
- **Requirement trace outranks blast radius.** A large cone means being wrong is
  expensive; a requirement means being wrong is *disqualifying*. Cheap wrong
  work that nobody promised anyone is the least urgent kind.
- **Hazards and stubs are debt, not defects**, so they sit below the verdicts —
  but above nothing, because they are the only terms that see the failure modes
  the chosen physics is structurally blind to. The v0.1 attention port had no
  access to either.
- **Age is a tiebreaker, never a driver.** Evidence going stale is a reason to
  look, not a reason to panic.

Normalization is the load-bearing design choice. The v0.1 reference summed a
raw downstream *count* into the score, which makes it unbounded, incomparable
between projects, and dominated by whichever graph happens to be deep: in a
50-node chain the cone term alone reaches 49 and no weight on any other signal
can be read as meaning anything. With every term in [0, 1] a weight means what
it says in every project, and the table above can be read as a policy rather
than as a fitted constant.

Two constants are not weights and are documented separately. `RISING_BUMP =
0.25` scores a summed `<=` budget with unvalued leaves as if it were a quarter
further along — direction as well as level — small enough never to invert a
real usage gap. The graded target values (1.0 / 0.4 / 0.15) put a band across
the line firmly between "meets" and "violates", where a reviewer's decision
belongs.

## Consequences

- **Evidence age is measured inside the lock, never against wall-clock.** A
  ranking that changes because a day passed is not reproducible and cannot be
  pinned by a conformance case; drift *relative to the program* is also the
  signal that was actually wanted. When no history exists at all, every node
  scores zero rather than one — a term that fires on everything ranks nothing.
- **Margin pressure attaches only to nodes that can move the number**: the
  geometry core whose locked mass is a rollup leaf, and its ancestors. An
  analysis that cannot change a budget does not inherit its urgency; the cone
  term already carries "many things depend on me". Where a leaf has no value at
  all the budget has no verdict, so the node that would produce it scores the
  maximum — the same rule that makes an unvalued leaf a top measurement.
- **Info-value ranks *declared* ignorance and says so.** It cannot price the
  unmodeled (spec §10.6). A design that declares everything exact gets UEL0902,
  not a short list.
- **`--sensitivity` is opt-in.** Scaling tightening by measured elasticities
  (v0.6's perturbation machinery) is the honest reading of "expected envelope
  tightening" — a 15 % band on a superlinear input is not a 15 % band
  downstream — but it costs real core runs and needs a fresh lock. The default
  stays free and structural.
- **Both queries are read-only and gate nothing.** They never touch the lock,
  never reorder execution, and their diagnostics are info-severity. The failure
  mode of a bad ranking is wasted attention, not a wrong artifact.

## Revisit

- **Sensitivity-aware ranking by default**, once elasticities are cached in the
  lock rather than recomputed: the structural fence term is a proxy for "this
  input matters", and a measured elasticity is the real thing.
- **Cost on the denominator.** The queries rank value, not value-per-dollar or
  value-per-week. A test campaign's cost and latency are exactly the terms that
  make an oracle slow, and neither is currently declarable.
- **Portfolio effects.** Measurements are priced one at a time; two candidates
  feeding the same fence are individually valuable and jointly redundant.
- **Requirement criticality is currently binary-plus-sole-source.** A
  requirement's own weight (safety-critical vs convenience) is not declarable,
  and should be before this term is trusted to arbitrate between programs.

## Alternatives rejected

- **Fold ranking into `uel build`'s order.** Rejected: build order is a
  correctness property (dependencies), and value order is advice. Mixing them
  would let a heuristic decide what executes, which is exactly the authority
  this module must not have.
- **Raw counts, as in the v0.1 reference.** See above — unbounded scores make
  the weight table uninterpretable and unportable.
- **Emit the economics diagnostics from `uel check`.** Rejected: it would put
  "this work is low value" in the same channel as "this graph is wrong", and
  the merge gate would start carrying opinions.
- **Wall-clock staleness age.** Rejected: unreproducible, and it measures the
  calendar rather than the program.
