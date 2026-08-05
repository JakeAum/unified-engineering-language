# Gap analysis — from the v0.1 kernel proof to a continuously running agent org that outperforms a human one

*Written post kernel-proof against spec Draft 0.1 and program Draft 0.1.
Companion to `leverage-v0.1.md`: that document records what the substrate
does; this one records the distance between that and the program's implied
end state — AI engineering agents, running continuously, whose
design-build-test loop beats a large human organization's. Standing
strategy document; amend it the way decisions are amended, with evidence.*

*Status (2026-08-05): moves 2, 3, and 5 of §2 shipped as ADR-0005 (`uel stale
--rank`, `uel query info-value`, `uel agenda`, candidate entailment rules);
move 1 stood up per `docs/org/user-org-loop.md`; move 4 triggers on the next
genuine merge conflict (program §8 R7).*

---

## 0. The frame: why agentic coding already works, and what that predicts here

Agentic code models crossed human-competitive thresholds wherever software
handed them a **fast, cheap, mechanical oracle**: compile + tests close the
loop in seconds, so a model iterates to correctness inside one context
window, and parallel agents can trust each other's work because CI re-checks
it for free. Physical engineering has neither property. The oracle is a test
stand that answers in weeks; the verification knowledge is tribal; a change's
blast radius is negotiated in meetings.

UEL's bet (spec §1.1) is to *manufacture* the software-shaped oracle for
hardware — units, conservation, envelopes, DFM as compile-time checks — and
to make knowledge durable and trustable — content-addressed claims,
provenance, calibration write-back. The v0.1 kernel proof demonstrates the
mechanism. The strongest current evidence for the thesis is this repository
itself: constitution → kernel proof in eleven merges by the agent org the
program document describes. But that run happened in the fast-oracle domain
(software, where the conformance suite answers in milliseconds). R2 — the
program's standing empirical risk — is precisely whether the leverage
survives a slow oracle.

Between the v0.1 substrate and the end state stand six gaps. They are
ordered by how much of the distance each one covers.

---

## 1. The six gaps

### G1 — Nothing runs continuously

The system is batch: `uel check/build/stale` execute when invoked, and
nothing invokes them. There is no event loop (a push, a landed measurement,
a decayed distributor quote, a filed issue → work), no standing agent
sessions, no issue channel with a Product agent behind it. The org chart of
program §3.2 exists as governance text, not as running contexts. The word
"continuous" in the end state is currently carried entirely by the human who
types the next command. Everything downstream of Stage 3 in the bootstrap
plan — north-star telemetry, adoption depth, the §6 kill criteria — is
**unevaluable** until agents live in the loop. This is the binding gap: not
capability, but existence.

### G2 — Leverage is measured on a denominator that was never the human bottleneck

`leverage-v0.1.md` is honest about scope, and the honesty deserves sharpening:
the recorded numbers (53 ms incremental vs 249 ms cold; 15 ms pre-solver
defect capture) measure **re-execution**, and re-execution is not why human
programs slip years. Human orgs pay for: (a) change-impact *negotiation*
(meetings, not CPU), (b) decision latency (reviews, boards), (c) oracle
latency (build and test campaigns), (d) rework from late-discovered
incompatibilities. Scenario 2 proxies (a) — "the ripple is computed, not
remembered" genuinely deletes a meeting class — and UEL0501/0502 attack (d)
mechanically. But the mapping from "1/7 invalidated in 53 ms" to "days of
impact-assessment meetings avoided" is asserted, not measured, and (b) and
(c) are untouched by the substrate so far. Closing R2 requires measuring the
human-cost denominators, not accelerating the machine numerators further.

### G3 — The front of the loop is recorded but not load-bearing

The kernel grades *finished* claims. It does not host the activity that
precedes them: candidate generation, trade studies, competing proposals over
shared resources. Spec §10.5 names this honestly — compile time detects the
conflict; nothing decides it — and program R7 already prescribes the
battle-test (resolve the org's own merge conflicts by recorded argument
before adjudicating hardware). At a large organization, conflict resolution
*is* the organization: design reviews and change boards are where the
expensive people spend their hours. Until competing bindings and their
resolution are graph objects with the §3.1 argument structure, the most
expensive human ritual has no substrate replacement.

### G4 — The back of the loop is throttled by the oracle, and nothing chooses experiments

Reality answers in weeks, which means **oracle contacts are the scarce
resource**, and the way a loop with a slow oracle gets faster is by making
each contact maximally informative. Nothing in spec, program, or roadmap
computes the information value of a proposed test. The graph already carries
everything needed — uncertainty bands, provenance, consumer cones,
margins — but "which single measurement most tightens the envelopes that are
currently eating margin" is not a query. In v0.1 the calibration campaigns
are hand-authored JSON; verification obligations (spec §8.1) are not yet
compiled into ranked test proposals. This is the largest blind spot in an
otherwise self-aware document set: v0.2 lists FMU transport and SysML import
before it lists experiment selection, which is backwards for a program whose
north star is iteration leverage against a slow oracle.

### G5 — The unmodeled is where the senior engineers actually are

Spec §10.6 says it plainly: the dominant cause of loss is unsafe interaction
among components that each meet spec, the checker enforces only *declared*
assumptions, and the entailment web is hand-authored (ADR-0003, residual
doubt 2). This is exactly the terrain where senior humans at large orgs earn
their comparative advantage — smelling the interaction nobody declared. The
mitigations are named (perturbation testing at envelope boundaries,
behavior-trace exploration, vision-agent review of projections) and none are
built. Until adversarial discovery exists, "outperform human engineers"
honestly means: *outperform on everything downstream of specification, while
specification and seam-ownership remain human*. That boundary should be
stated, held, and pushed back deliberately — not blurred.

### G6 — Scale, ergonomics, and the empty side of the moat

Seven analyses and a 50-node demo versus the 10⁴–10⁶ mixed-fidelity nodes of
a real program; a zero-dependency Python reference kernel (ADR-0002, the
right call) versus the query-based incremental engine of program §4; no LSP,
no remote execution, no surrogates — all named for v0.2/v0.3. And the moat —
the calibration flywheel — currently has no flow through it: adoption depth
is 7/7 by construction because the same effort built the tool and the slice.
None of this is research risk; all of it is engineering that should be
*pulled by observed failure* (program §9 discipline), not pushed by roadmap.

A design heuristic for everything in G6 and beyond: **build what appreciates
as models improve, not what compensates for their weakness.** Durable
calibrated memory, verification asymmetry, governance, instrumentation —
these grow more valuable as cognition gets cheaper, because coordination and
calibration become the binding constraints. Diagnostic hand-holding and
fix-loop scaffolding depreciate with every model generation. When two
features compete for budget, fund the appreciating asset.

---

## 2. What doubles leverage next

Amdahl's argument, using the program's own numbers: inside one iteration the
substrate now costs milliseconds, agent cognition costs minutes-to-hours of
context spend, and the physical oracle costs days-to-weeks. Further substrate
speedups move nothing. The next doubling must come from the two expensive
terms — **agent attention** and **oracle contact** — neither of which the
substrate currently manages. The graph schedules cores; nothing schedules
cognition or experiments.

Ranked; each with the cheapest first step.

1. **Stand up the continuous loop (Stage 3, now).** One standing user-org
   session, woken by events (push, calibration landing, schedule), that
   walks the stale frontier of apache-one, does real work, and files typed
   issues; a Product agent behind the channel; north-star telemetry live
   from day one, including the G2 denominators (wall-clock and context spend
   per merged claim, not just core-seconds). Iterate the slice under
   injected requirement changes and test campaigns with realistic latency.
   Everything else on this list is speculation until the kill criteria of §6
   are evaluable. *First step: one scheduled session per day against the
   slice; measure iteration 2 vs iteration 1. The session infrastructure
   that built this repo is the runtime; it is already commodity.*

2. **Schedule cognition: extend staleness to priority.** `uel stale` answers
   *what* is invalid in topological order; it should answer *what matters*:
   rank the stale frontier by margin erosion, requirement criticality,
   downstream cone size, staleness age. Margins and cones are already
   computed; the ranking is a join over existing data. This is the piece
   that makes "continuous" meaningful — an agent waking up should be handed
   the highest-value stale node, not the next one in topo order. *First
   step: `uel stale --rank`; make it the user org's standing work queue.*

3. **Make experiments a computed choice.** Add information-value machinery:
   for each candidate measurement, expected envelope tightening times the
   weight of the consumers it feeds — even the crude form (interval width ×
   consumer-cone size × margin pressure) beats hand-picking campaigns.
   Compile verification obligations (spec §8.1) into *ranked* test
   proposals. This is the direct attack on the slow oracle, and it belongs
   in v0.2 above FMU and SysML plumbing. *First step: `uel query info-value
   <quantity>`; re-order the roadmap accordingly.*

4. **Prototype governance-by-recorded-argument on our own merges (R7).**
   Competing proposals as first-class graph objects: two branches touching
   one budget produce a conflict node carrying both sides' intent, framing,
   and judgment; resolution is recorded ADR-style and survives as
   precedent. Battle-tested where program §8 says to — on the software org's
   own conflicts — before it adjudicates hardware. This is the substrate
   replacement for the design review, which is the most expensive ritual at
   the organizations the end state names. *First step: the next genuine
   merge conflict in this repo gets resolved through the mechanism instead
   of by the integrator's fiat.*

5. **Grow the entailment web empirically.** Every discrepancy event, every
   red-team escape, every declined-then-refiled issue emits a *candidate*
   entailment or exclusion rule into the claims taxonomy, with provenance,
   reviewed like any merge. The hand-authored web (ADR-0003's residual
   doubt) becomes a calibrated, compounding asset — the org's accumulated
   physics judgment, outliving every context window. This is the moat
   against "a better model ships next quarter": weights do not accumulate
   *this program's* calibrated physics; the graph does. *First step: emit a
   candidate-rule stub automatically from the next UEL0803 discrepancy.*

Deliberately below the fold: LSP, the Rust port, remote execution, SysML
bridges. All real, all v0.2/v0.3, all scale *existing* leverage rather than
create the missing kind — and per §5.3, work without a linked failure is
presumptively dead. Let the continuous loop generate the failures that pull
them in.

---

## 3. The one-line answer

The substrate has made the cheap half of the loop free; the gap to
"continuous agents outperforming a human org" is that nothing lives in the
loop yet, and the two resources that actually bound it — agent attention and
oracle contact — are unmanaged. Stand the loop up, then schedule cognition
and experiments the way v0.1 already schedules cores. The physics is the
type checker; make the economics the scheduler.
