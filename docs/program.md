# UEL Program Plan

**Program management document — how the language gets built**

*Status: Draft 0.1 — companion to `spec.md` (Draft 0.1, August 2026)*
*The spec says what UEL is. This document says who builds it, in what order, under what authority, and how we know it's working.*

---

## 1. Program charter

### 1.1 Mission

Build and maintain UEL — the content-addressed engineering language defined in `spec.md` — as open-source infrastructure for AI engineering agents. The program is complete in no version; it is *succeeding* whenever its users' iteration leverage measurably improves.

### 1.2 Structure: two organizations, one boundary

| | **Software Org** ("the company") | **Hardware Org** ("the users") |
|---|---|---|
| Mission | Build and maintain UEL | Fly the vehicle programs (testbed: Apache One; target: supersonic program) |
| Staffed by | Autonomous Claude agents | Autonomous Claude agents (engineers) |
| Touches | Code, spec, conformance suite | Physical hardware, test stands, UEL as a tool |
| Graded by | User adoption + issue flow | Physics |
| Never does | Design hardware, tune the users' models | Modify UEL internals |

The separation is load-bearing, not organizational hygiene. It is the program's oversight mechanism: **the software org cannot grade its own product** (users do, via adoption and issues), **and the users cannot grade themselves** (the vehicle does). The accountability chain terminates in physics. Producer and consumer share no context, no roadmap authority over each other, and communicate only through the public interface defined in §7.

### 1.3 Commercial posture

Internal, non-profit, open source. No revenue, no contracts, no external customers. This removes most legal surface area; what remains (license, maintainer-of-record, contribution terms) is settled once at bootstrap (§9) and rarely revisited.

### 1.4 Non-goals

The program does not build: hardware, vehicle models, a commercial product, a certification authority, or a general agent-orchestration platform. Anything not on the critical path to the north-star metric is presumptively dead (§5.3).

---

## 2. Authority model

### 2.1 The principle

Supervision (checking work) is engineered to approach zero human hours. Authority (owning purpose) is retained by the human principal and is deliberately thin. Everything between those two poles is executable process.

### 2.2 Executable authority: the merge gate

The organization's operational boss is a machine: **conformance suite + compile-time checker + decorrelated adversarial review, gating every merge.** No agent's claim of completion means anything; only what passes the gate exists. Three disciplines keep the gate honest:

1. **Spec-before-code by separate lineages.** Conformance tests for a feature are authored by agents sharing no context or prompt ancestry with its implementers.
2. **Decorrelated review.** Reviewers use different model families / framings than authors wherever available; where unavailable, differently-situated contexts (different boot library slices, adversarial role prompts).
3. **Verification asymmetry as a design rule.** Every task is decomposed until checking it is much cheaper than doing it. Tasks that can't be decomposed this way are escalated, not merged on trust.

### 2.3 Human authority points (the residue)

The principal (chief engineer / program owner) retains exactly four standing items. Steady-state cost: approximately zero hours per week.

| Authority | What it is | Exercised when |
|---|---|---|
| Charter amendment key | The org cannot rewrite §1 of this document or §1 of spec.md | Rarely; by written amendment |
| Compute budget | Funding the substrate = holding the kill switch; made explicit per phase (§6) | Phase boundaries |
| Sampled audit | Random deep-dives into merged work; the human is *differently wrong* than any AI reviewer | ~1 hr/week, unannounced |
| One-time formalities | License, maintainer-of-record, contribution terms | Bootstrap only |

Everything else — task assignment, triage, roadmap sequencing within a phase, role creation, playbook edits — is internal to the software org.

### 2.4 What the org may never do autonomously

Amend the charter; expand scope beyond §1.4; force a breaking migration during a user's active test campaign (§7.3); disable or weaken the merge gate; grade its own north-star metric (the metric is computed from user-org data the software org cannot write).

---

## 3. Organization design

### 3.1 Coherence as an engineered artifact

Headcount is free; **coherence is the scarce resource.** Agents get no hallway osmosis, so shared understanding is maintained as three versioned artifacts, loaded by every context at boot:

- **The constitution** — `spec.md` + this document. Change-controlled (§2.3, §8.2).
- **The decision log** — every architectural choice recorded as an analysis node: intent, framing, alternatives, judgment. Settled decisions are not re-litigated; they are amended with new evidence.
- **The boot library** — curated, distilled context (current architecture map, active playbooks, open-problem status). Owned by the Historian (§3.2). Pruned as aggressively as it is grown.

Coherence decay across parallel contexts is the failure mode that kills agent organizations. The Historian role, the decision log, and the boot library exist to fight it; the sampled audit (§2.3) watches for it.

### 3.2 Roles

Roles are contexts + toolsets + permissions, spawned in seconds and added **only when an observed failure earns them** (§9). Steady-state roster:

| Role | Cardinality | Cadence | Owns |
|---|---|---|---|
| Architect | few | slow, long-context | Constitution coherence; design review of kernel-touching changes |
| Implementer | many | short-lived | Leaf tasks against typed acceptance criteria |
| Test author | few | independent lineage | Conformance suite; never shares context with implementers |
| Red team | standing | continuous | Breaking the checker, gaming the suite, adversarial inputs |
| Integrator | one | continuous | The merge gate; the staleness frontier of the build graph |
| Historian | one | continuous | Decision log, boot library, distillation of merged work |
| Product agent | one | continuous | North-star metric; kill authority over off-path work; user-issue triage (§7.2) |

### 3.3 Task anatomy

Every task carries: typed acceptance criteria (linked to conformance tests), a compute budget, kill criteria, and a lineage tag (for decorrelation checks). Work without all four does not enter the queue. The org runs on UEL's own primitives — tasks as graph nodes, claims with provenance, content-addressed everything — from day zero (§9.1). Dogfooding is the only honest test environment available before external users exist.

---

## 4. Work breakdown and build order

The compiler is a query-based incremental engine (Salsa model): the compiler, the LSP server, and the staleness oracle are one engine. Rust kernel; Python as the blessed core/SDK language. Nothing in phases 1–5 is research; the two research risks stay quarantined in the risk register (§8) and are attacked in parallel by de-risk spikes, not on the build critical path.

### Phase 1 — Semantic schema + conformance skeleton

The data model of the graph (components, ports, quantities, claims; shell/core; hashing rules) defined *before* concrete syntax, as schema + a WASM-style conformance test suite that all future work is graded against. **Exit:** schema frozen for the edition; suite runs in CI; ten realistic model fragments round-trip.

### Phase 2 — Parser, resolver, units checker

Hand-written recursive-descent parser + tree-sitter grammar; name resolution; units/dimensions as a Kennedy-style free-abelian-group checker extending HM. Structured JSON diagnostics as a first-class output — agents iterate against errors, so error quality is a feature, not polish. One zero-config formatter. **Exit:** checker gates a live CI; diagnostics round-trip through an agent fix-loop on seeded errors.

### Phase 3 — Hashing, staleness, local scheduling

Merkle-DAG IR (Unison identity + Nix derivations); content hashes covering resolved inputs, envelope, core, pinned tool versions; staleness propagation; local Python scheduler executing analysis cores. **Exit:** a change to an upstream quantity mechanically flags every stale downstream analysis in a 50-node demo graph; re-run restores freshness.

### Phase 4 — Conservation, envelopes, geometry assertions

Port/conservation checking via sparse incidence matrices per domain; envelope value-predicates lowered to SMT (Z3, QF_LRA first, cached by hash); structural-claim entailment table (datalog-style); Build123d geometry nodes with mandatory topological assertions; DFM ruleset activation at binding. **Exit:** the spec §5 composition rule (guarantee covers assumption, or compile error with stated reason) works end-to-end on the de-risk pair set (§8.1).

### Phase 5 — Surfaces and scale

LSP; compiled projections (work instructions, BOMs, ICDs) stamped with graph hash; remote execution for heavy cores (Bazel Remote Execution API + CAS); SysML v2 import scaffolding. **Exit:** vertical-slice readiness — the user org can model, check, build, and write back on a real subsystem.

### Continuous — Vertical slice and the leverage measurement

From Phase 3 onward, every capability lands on one real, physically tested, brutally cross-coupled artifact from the user org. The program's justifying claim (spec §10.2) is measured here, not asserted: **iteration 2 vs. iteration 1, instrumented.**

---

## 5. Metrics

### 5.1 North star

**User-org iteration leverage:** cycle time and defect-escape rate of the hardware org's design-build-test loop, iteration-over-iteration, on the vertical slice. Computed from user-org telemetry; the software org has read-only access and cannot write to it (§2.4).

### 5.2 Supporting indicators

Adoption depth (fraction of user-org analyses living in the graph vs. outside it); issue flow health (time-to-triage, time-to-fix, reopen rate); staleness honesty (fraction of downstream consumers correctly flagged when upstream changed — measured by seeded perturbations); gate integrity (red-team escapes per phase); coherence (re-litigation rate of settled decisions — a Historian metric).

### 5.3 Anti-metrics

The org's natural failure is infinite competent busywork. The Product agent holds standing kill authority over: refactors without a linked user issue or open problem, speculative features, and tooling for problems nobody has filed. Every kill is logged with reasoning; the human sampled audit reviews kills as well as merges.

---

## 6. Compute budget and kill criteria

Compute is allocated per phase against exit criteria, released at phase boundaries by the principal (§2.3). Within a phase, the Product agent sub-allocates per task. Standing kill criteria for the program itself, evaluated at each phase boundary:

1. **Leverage falsified:** two consecutive vertical-slice iterations show no improvement after Phase 5 machinery is in use → stop, run the spec §10.2 post-mortem, decide rework-vs-terminate at charter level.
2. **Envelope formalism fails de-risk** (§8.1) → halt Phase 4, rework foundations; do not build around the hole.
3. **Adoption refusal:** user org, given a working Phase 5, chooses to route around UEL for a majority of new analyses → the product thesis is wrong in a way issues can't fix; escalate to charter review.

---

## 7. The user interface (org-to-org)

### 7.1 Channel

A single public issue channel. Users post gripes, defects, and requests as typed claims with provenance ("envelope checker rejected valid spar model; cost us test window W12; repro attached"). The software org triages; nothing else crosses the boundary. No shared standups, no embedded liaisons — situational decorrelation is the oversight mechanism and is preserved by keeping the wall thin and formal.

### 7.2 Triage discipline

The Product agent owns triage. Every issue receives: a recorded judgment (accept / decline with reasoning), a severity linked to user impact on the north star, and — if accepted — a fix hashed against the issues it resolves. Declines are data too; a pattern of declined-then-re-filed issues is a coherence alarm.

### 7.3 Edition governance

Users are agents *mid-flight-program*; a breaking change invalidates cached analyses across their content-addressed graphs. Therefore: Rust-style versioned editions; deprecation windows measured in user iterations, not calendar time; migration tooling ships *with* the breaking change, not after; and a hard rule — **no forced migration during an active test campaign** (§2.4). The org boundary gets the same machinery as the calibration loop: issues in, judgments recorded, fixes hashed against complaints.

---

## 8. Risk register

Ranked. R1 and R2 are the only research risks; everything else is engineering or organizational.

| # | Risk | Type | Mitigation / de-risk | Trigger |
|---|---|---|---|---|
| R1 | Envelope formalism for structural claims has no workable calculus (spec §10.1) | Research | Spike: encode 10 real cross-domain analysis pairs in the draft formalism before Phase 4; <50% fit → rework foundations | Phase 4 entry |
| R2 | Leverage thesis false (spec §10.2) | Research/empirical | Vertical slice instrumented from Phase 3; measured, not asserted | §6.1 kill criterion |
| R3 | Coherence decay across parallel contexts | Organizational | Historian + boot library + decision log; re-litigation metric; sampled audit | Re-litigation rate rising |
| R4 | Gate gamed (tests satisfied, intent violated) | Organizational | Red team standing; lineage-separated test authors; human audit decorrelation | First red-team escape post-merge |
| R5 | Hash/tolerance semantics unsound (spec §10.3) | Engineering | Seeded-perturbation staleness testing (§5.2); conservative over-invalidation default | Staleness honesty < 100% |
| R6 | Agent ergonomics wrong (spec §10.4) | Engineering | Ergonomics experiments before syntax freeze (Phase 2); diagnostics fix-loop testing | Agent fix-loop failure rates |
| R7 | Governance of conflicting proposals unresolved (spec §10.5) | Research-adjacent | Battle-test resolution-by-recorded-argument on the org's own merge conflicts before it must adjudicate hardware | First unresolvable conflict |
| R8 | Busywork drift | Organizational | Product agent kill authority; anti-metrics (§5.3) | Kill-log review |
| R9 | The unmodeled (spec §10.6) | Permanent | Not solvable; perturbation testing, vision-agent review, honest labeling — the green checkmark is never sold as safety | Standing |

---

## 9. Bootstrap plan

The org and the product grow together, from observed failures — an org chart designed in advance is speculation; one grown from failures is calibrated. Which is the thesis of the language, applied to its builder.

### Stage 0 — Constitution

One orchestrator context. Ratify: this document, spec.md, license and maintainer-of-record (§2.3 formalities), the semantic schema draft, and the conformance-suite skeleton. The org's own work tracking is bootstrapped *in* UEL-shaped primitives (tasks as nodes, decisions as claims) even before the compiler exists — plain files in the content-addressed repo.

### Stage 1 — First blood

Five agents: one architect, three implementers, one test author (separate lineage). Ship Phase 1–2 behind the merge gate. The Integrator role is the orchestrator wearing a second hat until merge volume earns a dedicated context.

### Stage 2 — Roles earned by failures

Add the **Red team** at the first gamed test that slips through. Add the **Historian** at the first re-litigation of a settled decision. Add the **Product agent** when the first speculative task burns budget without a user or open-problem link. Each addition is logged as a decision node: the failure, the role, the expectation.

### Stage 3 — First contact

Phase 3–4 land; the user org begins the vertical slice; the issue channel opens; north-star instrumentation goes live. From here the program is graded externally and this document's §5–§7 machinery takes over.

### Stage 4 — Steady state

Phase 5; editions; human attention at the §2.3 floor: phase-boundary budget reviews and the weekly sampled audit. The program is now what it builds: a calibrated loop, corrected by the reality it touches.

---

## 10. Change control for this document

This document is itself content-addressed and versioned. §1 (charter) and §2.3 (authority points) change only by principal amendment. Everything else is amendable by the org through the decision log, subject to the merge gate, with the Historian maintaining the diff history. Process changes are treated exactly like code: proposed, reviewed by decorrelated contexts, merged, and — when they fail — reverted with a recorded post-mortem that edits the playbooks.

---

*The company is the first UEL instance. If the coordination substrate cannot coordinate its own builders, that is the cheapest possible place to find out.*
