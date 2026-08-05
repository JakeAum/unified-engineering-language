# UEL — Unified Engineering Language

**A language design document**

*Status: Draft 0.1 — synthesis of design conversations, August 2026*
*Working name: UEL. Naming is deferred; the ideas are not.*

---

## 0. One-sentence definition

UEL is a content-addressed, typed graph of engineering claims — components exchanging conserved quantities across ports, analyses justifying design decisions, and assumption envelopes continuously calibrated by test data — authored and consumed primarily by AI engineering agents, and compiled outward into the artifacts (geometry, code, work instructions, datasheets, certification views) through which a design is born into the physical world.

---

## 1. Purpose and philosophy

### 1.1 What this language is for

Engineering of highly integrated systems fails at the seams. A change to wing loading propagates into propulsion, flight controls, structures, thermal, and cost — and today that propagation happens through meetings, tribal knowledge, and luck. Existing systems-engineering languages (SysML v2 foremost) describe systems but do not *bear load*: nothing downstream depends on the model, so the model drifts, and the engineers doing real design ignore it.

UEL exists for a near future in which the bulk of engineering labor is performed by intelligent, text-native AI agents working in parallel. In that world the binding constraints change:

- Agents do not need diagrams. They need **strong types, local checkability, clean diffs, and composability**.
- Agents do not need help *thinking* across disciplines — a capable agent holds aerodynamics and electronics in one context the way a great engineer holds them in one head. What agents need is a way to **trust each other's work without redoing it**, and a way for knowledge to **survive across agent generations and context windows**.

**UEL is therefore a coordination and memory technology, not a cognition technology.** Its job is to let agent #400 consume agent #17's stress analysis without re-derivation, and to let a calibrated envelope from last year's test campaign outlive every context window that touched it.

### 1.2 What this language optimizes

Not formal perfection. **Iteration leverage**: each design-build-test cycle must make the next cycle cheaper. The model is not proven; it is *calibrated* — continuously corrected by the tests it generates. The measure of success is that iteration N+1 is measurably faster than iteration N, or catches a failure that iteration N missed.

### 1.3 What this language is not

- **Not a grand ontology of physics.** History is unambiguous: comprehensive ontologies lose to minimal checkable protocols (bond graphs lost to domain tools; the semantic web lost to REST+JSON). UEL ships a tiny non-negotiable kernel and lets richer ontology *emerge* from what agents build, harvested and standardized after the fact.
- **Not a formal-verification system.** Conservation checks and envelope compatibility are enforced mechanically; everything empirical is an uncertainty-carrying estimate. The physical world is not compositional, and the language does not pretend otherwise.
- **Not a SysML extension.** SysML v2 owns no runtime and not our users. UEL clean-slates the kernel, steals KerML's good ideas (the specialization lattice, library grounding) as inspiration, and speaks SysML only at the boundary (§9).
- **Not a gatekeeper.** UEL is the substrate under a build-fly-learn loop, not a bureaucratic checkpoint in front of it. Assumptions are declared *loose* and *fast*; reality does the tightening.

### 1.4 Design principles

1. **Load-bearing or dead.** Every element of the model must generate or constrain a real artifact. Anything that is merely descriptive will drift and must be cut.
2. **Unified, not split.** One graph. Manufacturing cost, COTS prices, lead times, test data, and DFM constraints live in the same graph as requirements and physics — because manufacturing realities drive the platonic idea of the system. There are many *views*; there is no second model.
3. **Reality is the oracle.** Hard checks for what mathematics guarantees (conservation, units, references). Calibrated confidence for everything empirical. Test data always wins an argument with a model.
4. **Compiled projections, never authored artifacts.** Work instructions, drawings, and datasheet views are compiled from the graph and stamped with the graph hash they came from. Hand-editing an output is the drift failure mode; it is prohibited by construction.
5. **Minimal kernel, emergent vocabulary.** The kernel is small enough to hold in an agent's context. Domain libraries grow around it.
6. **Assumptions are load-bearing type information.** The validity envelope of every model is explicit, checkable, and versioned — the margin-of-the-notebook made mechanical.

---

## 2. Core ontology

The kernel admits exactly four kinds of thing: **components**, **ports**, **quantities**, and **claims** (analyses). Everything else is library.

### 2.1 The graph

An engineering artifact is a *thing that occupies a region of spacetime and exchanges conserved quantities with its neighbors*. The model is a directed multigraph:

- **Nodes** are components (at some abstraction level) and analysis nodes (§3).
- **Edges** are connections between ports, and dependency references between analyses and the values they consume.

Structure, behavior, energy flow, state, and cost are not separate pillars; they are views over this one graph.

### 2.2 Ports

A **port** is a boundary where a conserved quantity crosses a component's surface. Following bond-graph insight, every physical port carries an **effort/flow pair** whose product is power:

| Domain     | Effort        | Flow            |
|------------|---------------|-----------------|
| Electrical | voltage       | current         |
| Mechanical (translation) | force | velocity |
| Mechanical (rotation)    | torque | angular velocity |
| Hydraulic  | pressure      | volumetric flow |
| Thermal    | temperature   | entropy flow    |

Two additional port classes:

- **Material ports** carry mass flow with composition.
- **Data ports** carry typed information flows (signals, messages, buses) with rate and latency attributes. Data is not conserved; data ports are typed by protocol/schema instead of by balance.

**Kernel invariant (non-negotiable):** at every connection and across every component boundary, conserved quantities balance. Energy in = energy out + storage + dissipation; mass likewise; charge likewise. Port balance is checked at compile time (§5) before any solver runs. *The physics is the type checker.*

### 2.3 Abstraction levels and binding

Every component exists at a declared **abstraction level**, and the same identity may be held at several:

1. **Functional** — what it does: "transfer this load," "regulate 3.3 V at ≤500 mA," "move this fluid." Process-free, geometry-free. Ports and required envelopes only.
2. **Behavioral** — how it responds: transfer functions, state machines, characteristic curves.
3. **Physical** — what it is: geometry (§6), materials, a bound realization (a specific machined part, a specific COTS device).

A **binding** is a checked refinement edge from a higher level to a lower one: platonic component → candidate realization. Bindings are where reality's rulesets activate:

- Binding to a **manufacturing process** (`cnc_3axis`, `injection_molded`, `sheet_bend`, `SLA`, …) activates that process's DFM ruleset as compile-time envelope checks (§7.1).
- Binding to a **COTS part** imports the part's datasheet interface (§7.2) and checks it against the functional requirement's envelopes.

The same functional component may carry different bindings in different configurations (machined billet for flight-test article #3; molded for unit #100). The functional contract above the binding is untouched; the checks below it swap automatically.

### 2.4 Quantities: units and uncertainty as substrate

Every scalar/tensor value in the graph is a **quantity**: `(value or distribution, unit, provenance, timestamp, confidence)`.

- **Units are mandatory and checked.** Dimensional analysis is the miniature proof of this whole design — a tiny assumption-checking type system everyone already agrees is worth it. UEL extends the same bargain to everything else.
- **Uncertainty is first-class, not bolted on.** Real engineering runs on margins, and margins are how the *unmodeled* is survived. Point values are the degenerate case. Quantities default to intervals/distributions; rollups propagate uncertainty; **margin erosion is a computed, watchable property** of every budget.
- **Provenance is mandatory.** Every quantity points at its origin: a requirement, a datasheet page, a test measurement, an analysis output, an agent's estimate. "Where did this number come from" is a query, not an archaeology project.
- **Volatile observations decay.** Some quantities (prices, lead times, stock) are measurements of a changing world. They carry timestamps and decaying confidence, and are refreshed by instruments (§7.3, §8). A stale price is *stale* in exactly the same mechanical sense as a stale CFD case.

### 2.5 Assumption envelopes

Every model, analysis, and binding carries an **envelope**: the fence of assumptions inside which it is valid. A type in UEL does not name an object; it names *the assumption set under which a model of that object holds*. "Lumped-element resistor, valid below 100 MHz, T < 400 K" — the fence *is* the type.

Envelopes have two layers:

- **Value predicates** — constraints over quantities ("0 °C < T < 85 °C", "Mach < 0.3", "load < 2 kN"). Decidable by SMT; checked at compile time wherever inputs are statically known, asserted at runtime otherwise.
- **Structural claims** — statements about which physics was *dropped* ("rigid body," "adiabatic," "steady-state," "frictionless"). These are claims about model structure, not values. Their compatibility calculus is the language's foremost open research problem (§10.1). Draft 0.1 treats them as a declared taxonomy with hand-authored entailment rules ("frictionless ⇒ no joint heating") and *requires* them to be declared even where they cannot yet be fully checked — declared-but-unchecked beats undeclared.

**Envelope lifecycle:** envelopes are born *loose* (wide intervals, weak claims, authored fast) and are **tightened by calibration** (§8). An envelope is never "proven"; it has a confidence history.

**Composition rule:** when node B consumes node A's output, compile time checks that A's guarantee envelope covers B's assumption envelope (contract satisfaction: A's guarantees ⇒ B's assumptions). Incompatible envelopes are a compile error *with a stated reason* — "you modeled this beam as rigid; downstream flutter analysis requires its first bending mode."

---

## 3. The analysis node: engineering's unit of work

The real unit of engineering is not the part or the port — it is the **analysis**: an argument that a claim about the system is justified. UEL captures analyses as first-class graph nodes with a fixed epistemic structure and a uniform executable interface.

### 3.1 The epistemic structure: intent, framing, knowns, derivation, judgment

Every analysis records five things, and the two that current tools discard are the two that matter most:

1. **Intent** — the question this analysis exists to answer, linked to the requirement or decision it serves. ("Will the spar carry limit load at Mach 1 pull-up?") An answer detached from its intent is meaningless; intent is the root.
2. **Framing** — the creative act: chosen physics model, drawn boundary (the free body — what is inside, what becomes a boundary condition), and assumptions **with rationale**. Not just "rigid" but "rigid, *because deflection is not the question here*." The rationale is what lets a future agent decide whether the framing survives a design change.
3. **Knowns** — inputs as *references* into the graph (never copies), each with provenance and uncertainty.
4. **Derivation** — the equations, the solve, the tool run. Cheapest to capture, easiest to regenerate, least valuable. Fully recorded for reproducibility; never mistaken for the point.
5. **Judgment** — the sense-making: is the result physical, converged, sufficient, and does it answer the intent? Recorded explicitly, with the residual doubts. This closes the loop back to (1).

An analysis is therefore a small **argument** — claim, assumptions, evidence, verdict — that stays attached to what it analyzed and *knows when it has been invalidated*.

### 3.2 The executable structure: shell and core

Every analysis node has a **uniform shell** and an **opaque core**. The shell never scales with cost; a 100 ms Python script and a 10-hour CFD campaign are the same shape of thing.

**Shell (fixed, domain-agnostic, what compile time reads):**

| Slot | Content |
|---|---|
| `inputs` | typed references to quantities/geometry in the graph (pointers, not copies) |
| `envelope` | assumption envelope (§2.5), value predicates + structural claims + rationale |
| `hash` | content hash of the complete recipe: resolved inputs + envelope + core definition + tool/kernel versions |
| `outputs` | typed, unit-carrying quantities (and/or artifacts: fields, meshes) with uncertainty |
| `status` | `fresh` / `stale` / `running` / `failed`, plus provenance and judgment record |

**Core (opaque to the checker, variable in weight):** the executable recipe. For the bench: "run `spar_static.py`." For CFD: "generate mesh with this config; invoke the solver with this command; monitor; check convergence residual < 1e-5; extract Cp field and coefficients." The core also records execution provenance: tool, version, command line, wall clock, convergence evidence, raw output locations.

Compile time never opens the core. It checks only: references resolve; types and units line up; envelope contracts satisfied; hash current. All cheap, all static, no solver.

### 3.3 Fidelity ladders and surrogates

The same intent may be served by multiple analysis nodes at different fidelities (hand calc → panel method → RANS CFD), each with its own envelope and cost. A **surrogate** is a cheap fitted model over sparse expensive runs, carrying a validity domain; compile time reasons over the surrogate and the scheduler triggers the expensive solver only when a query leaves the surrogate's fence. Fidelity choice is thereby an explicit, recorded, revisitable decision.

---

## 4. Identity, change, and time: the content-addressed graph

### 4.1 Content addressing

Every node's identity-for-staleness is a **content hash** over its complete definition: resolved input values, envelope, core recipe, and pinned tool versions (CAD kernel, solver, library versions — a different kernel is a different artifact, exactly as in Nix). Human-meaningful names are aliases over hashes.

### 4.2 Staleness propagation

Change the outer mold line → geometry hash changes → every node referencing it flips `stale` → their outputs' hashes change → downstream flips stale, transitively. Compile time answers "what does this change invalidate?" in seconds by hash comparison alone, before any physics runs. **This is the direct mechanical answer to the tightly-coupled-subsystem problem**: wing loading touches propulsion and flight controls because the dependency edges say so, and the ripple is computed, not remembered.

### 4.3 Tolerance-aware equivalence (open design problem, §10.3)

Naive hashing makes everything permanently stale (floating-point noise, solver nondeterminism, mesh seeds); coarse hashing lets real changes slip. UEL requires **equivalence-classed hashing**: quantities hash within declared tolerances; "changed enough to matter" is a sensitivity question, so staleness may consult derivative/sensitivity information where available. Draft 0.1 rule: hash quantized values at a per-type declared tolerance; treat solver nondeterminism by pinning seeds; escalate to sensitivity-aware staleness in v0.2.

### 4.4 Compile time vs. model runtime

- **Compile time** (every diff, every merge; seconds; no solver): references resolve; units and dimensions check; port conservation balances; envelope contracts satisfied; DFM rulesets pass for bound processes; geometry assertions hold (§6.2); staleness set computed; budgets and margins re-rolled.
- **Model runtime** (scheduled; expensive): the scheduler walks the stale set in dependency order and re-executes cores — inline for cheap nodes, dispatched to compute for heavy ones, with `running` status polled by the graph. Compile time gates runtime: a 10-hour CFD case never launches on a design whose ports don't balance.

### 4.5 Concurrency and merge

The graph is stored as text (§5.1) under Git or equivalent: agents branch, diff, and merge at line level; compile time runs as the merge gate. Semantic conflicts that survive textual merge (two agents tightening the same budget incompatibly) surface as compile errors on the merged result. Resolution *policy* — whose change wins and why — is the governance open problem (§10.5).

---

## 5. Surface language

### 5.1 Requirements on the syntax

The customer is an AI agent; the syntax is optimized accordingly:

- **Plain text, line-oriented, diff-friendly.** No binary blobs in the source of truth (derived artifacts may be binary; they are outputs).
- **Locally checkable.** An agent holding one file plus the interface summaries of its neighbors can validate its work. Interface summaries are compact by design — context windows are a real resource.
- **Explicit over implicit.** Verbosity is cheap for agents; ambiguity is expensive. Every reference is qualified; every unit is written; every assumption is declared.
- **Executable-adjacent.** Analysis cores are ordinary code (Python-first); geometry is code (§6); the boundary between "model" and "program" is thin and typed, not a wall.

### 5.2 Sketch (illustrative, not final)

```
component MainSpar : functional {
  port root_attach : mechanical.translation { force: [0, 12 kN] ± cal }
  port skin_bond   : mechanical.distributed
  budget mass <= 240 g ± 10 g          # participates in vehicle mass rollup
  budget unit_cost <= 85 USD @ qty 25  # participates in cost rollup
}

binding MainSpar -> spar_v7 : physical {
  process cnc_3axis                    # activates DFM ruleset
  geometry code ./geom/spar_v7.py      # Build123d, §6.2
  material AL7075_T6 from lib.materials
}

analysis SparStaticLimit {
  intent  req.STR-014 "carry limit load, FoS >= 1.5"
  framing {
    model  beam.euler_bernoulli
    assume rigid_root   because "root fitting stiffness >> spar; see AN-009"
    assume static       because "gust transient covered by SparDynamic"
    envelope { load in [0, 18 kN], T in [-40, 70] degC }
  }
  knowns { load <- req.STR-014.limit_load ; section <- spar_v7.section_props }
  core   python ./analysis/spar_static.py
  outputs { FoS : dimensionless ± ; max_deflection : mm ± }
  judgment pending  # filled by the authoring agent on completion
}
```

### 5.3 Libraries

The kernel ships with: SI units and dimensions; the port domain table; a materials library schema; process/DFM rulesets as data (§7.1); a structural-assumption taxonomy with entailment rules. All are libraries, versioned and hash-pinned — none are kernel. Domain vocabulary is expected to grow bottom-up from real projects and be standardized retrospectively.

---

## 6. Geometry

Geometry is the primary artifact of hardware and the historical graveyard of modeling languages. UEL admits exactly **two classes** of geometry and refuses all others.

### 6.1 Class 1: imported static references

Vendor and legacy geometry (STEP et al.) is treated as a **vendored binary dependency with a datasheet**:

- The file is hashed once per version; re-import on hash change is ordinary staleness.
- A one-time analysis extracts a typed **interface summary** into the shell: bounding box, convex hull and/or decimated mesh (bounding boxes alone throw interference false-positives on anything non-boxy), mass properties (carried as *wide-uncertainty vendor claims* until measured), mounting datums and fastener features.
- Downstream consumes the summary, never the blob. Imported geometry is **frozen**: it can be placed, not iterated. The class boundary is honestly the boundary between what agents can evolve and what humans/vendors supply fixed.

### 6.2 Class 2: code-generated parametric geometry

Custom geometry is **defined by the code that generates it** (Build123d-class, Python). The code is canonical; the B-rep/mesh are derived, cached node outputs.

- Geometry participates in the graph as ordinary shell-and-core nodes: parameters in, solids/meshes/mass-properties out; parameter change → hash change → mesh stale → CFD stale, all the way down the mold line.
- **CAD kernel version is pinned inside the hash** (same code on a different OCCT is a different artifact).
- **Topological assertions are mandatory envelope elements.** Code-CAD's classic failure is late-binding selectors silently grabbing different edges after regeneration. Geometry scripts must assert their topological assumptions — "this selector returns exactly 4 edges," "this face remains planar" — so a regeneration that violates them is a compile-time failure, not a silently wrong part. *The envelope idea, applied to shape.*

### 6.3 Assembly

Assembly is pure data: transforms over geometry references. Compile time performs hull-level interference, mass/CG rollup, and datum-chain checks; full B-rep interference and tolerance stack are runtime analyses like any other. Known limit, stated plainly: heavily sculpted Class-A surfacing resists code-CAD and will tend to fall into Class 1, going dead to iteration. For airframe-class work Build123d's lofts and sweeps cover most needs; the day an agent must *iterate* geometry it can only *import* marks the current edge of the system.

---

## 7. Manufacturing, COTS, and cost — in the same graph

Unified, not split. Manufacturing realities drive cost; cost is relevant to the platonic idea of the system; therefore cost, procurement, and producibility are first-class citizens of the *design* graph, not a downstream department.

### 7.1 Process bindings and DFM rulesets

DFM knowledge is encoded as **process rulesets**: data-defined check libraries activated when a component binds to a process (§2.3). Examples for `cnc_3axis`: internal pocket radii ≥ cutter radius (and preferably ≥ standard cutter + margin so the tool sweeps rather than dwells); chamfers preferred over fillets on external edges; sharp internal corners are impossible and are auto-flagged; undercuts require declared setup changes; loaded internal corners *retain* fillets as stress relief — DFM rules and fatigue rules are checked together, because a rule that saves machining minutes by seeding a crack is not a rule. `injection_molded` swaps in draft angles, uniform wall thickness, and fillets-everywhere. Tribal shop knowledge becomes statically checkable claims — which is the point of the entire language.

### 7.2 COTS ingestion: the datasheet pattern

A datasheet is an imported static reference for a *component* — the same pattern as §6.1 geometry:

- Hash the datasheet once per revision; extract a typed **interface summary**: electrical/mechanical/thermal ports, absolute-max envelopes, footprint, mass, derating curves — each quantity with provenance pointing at the page it came from.
- The platonic component ("3.3 V regulator, ≤500 mA, these envelopes") **binds** to the realization ("TPS62130") exactly as a bracket binds to a billet part; compile time checks datasheet guarantees against required envelopes.
- Extraction is agent-performed and judgment-recorded; extracted values are claims with vendor-grade confidence until test data upgrades them.

### 7.3 Cost and lead time as flowing quantities

Cost is already one of the graph's conserved-ish quantities:

- **Unit cost rolls up assembly trees by summation**, exactly like mass. **Lead time rolls up as max-over-critical-path**, like timing analysis. Both are budgets with computed margins, visible to system-level trade studies as gradients ($/kg, $/W, weeks/part) alongside mass sensitivities. Cost-as-independent-variable, in the model instead of a divorced spreadsheet.
- **Price, lead time, and stock are volatile observations** (§2.4): timestamped, decaying-confidence measurements refreshed through distributor APIs. The calibration loop built for the test stand handles procurement without modification — the supply chain is just another instrument that measures reality and writes back. A stock-out flips cost rollups stale; staleness propagates to the system cost budget; an agent sees the margin erosion at the *architecture* level, months before a human buyer would.

---

## 8. The calibration loop: how reality writes back

The model generates the artifacts that test it; the results correct the model. This loop is the moat — a beautiful graph nobody calibrates is SysML with better types.

1. **Test generation.** Verification obligations attach to requirements and envelopes; agents compile them into test procedures, HIL configurations, instrumentation lists, and analysis nodes that will consume the data.
2. **Work instructions as instruments.** Build/assembly travelers are compiled projections (§9.1) *and* data-entry surfaces: each step is a place where a technician's measurement, substitution, shim, or "step 14 is impossible as written" lands back in the graph as an **as-built delta**. Without this, the twin becomes fiction precisely where it touches reality.
3. **Envelope tightening.** Test data updates quantities (Bayesian-style narrowing of intervals/distributions) and shrinks envelopes: "damping coefficient somewhere in this wide range" → measured band. Every tightening is a version; confidence has a history. The next agent inherits a tighter world — leverage, made literal.
4. **Discrepancy handling.** A measurement outside a model's predicted envelope is a first-class event: it flips the model's confidence, flags every consumer of that model, and opens an investigation node whose resolution is itself an analysis (intent: "why was prediction wrong").

**As-designed vs. as-built are both representable**: the graph holds the design configuration and per-serial-number delta overlays, so "the airplane we designed" and "airplane serial 003 as it actually exists" are distinct, queryable states.

---

## 9. Boundaries: projections and bridges

### 9.1 Compiled projections

One graph, many views. All human- and machine-facing artifacts are **compiled, never authored**: work instructions, assembly drawings and exploded views, ICDs, datasheet-style component summaries, BOMs, certification/traceability reports. Every projection is stamped with the source graph hash — "is this document current?" is a mechanical query, and a stale traveler on the floor is as detectable as a stale CFD case.

**Visual projections serve two audiences**: humans, and vision-capable agents. Renders and section views feed agent review passes that catch the class of absurdity (part floating in space, fastener through a coolant line) no port-balance check ever will. Budget render-and-look into the standard review loop.

### 9.2 The SysML v2 bridge

SysML v2 is a fine language to talk to and a bad foundation to stand on. Two one-way bridges:

- **Import:** a systems architect's SysML v2 model compiles into UEL scaffolding — interface definitions become typed ports with wide uncalibrated envelopes; requirements become intents attached to analysis obligations; allocations become subgraph boundaries. The architecture stops being a description and becomes **a contract the agents fill in**: the architect declares *what* without knowing *how*, and watches their architecture acquire depth, margin, and evidence.
- **Export:** graph state projects out as SysML views — requirement satisfaction, verification status, traceability — for auditors, primes, and certification bases that speak SysML.

### 9.3 Solver interfaces

FMI/FMU is adopted as **transport, not ontology**: a standard plug shape for co-simulation of system-dynamics cores. Everything FMI omits — fidelity, envelope, convergence criteria, coupling contracts — lives in the UEL shell wrapping the FMU. Field solvers (CFD/FEA) are wrapped directly as shell-and-core nodes (§3.2) without forcing them through a signal-shaped hole; surrogates (§3.3) bridge them into cheap reasoning.

---

## 10. Open problems (honestly held)

1. **Envelope formalism** — *the load-bearing research risk.* Value predicates are SMT-decidable; **structural claims** ("rigid," "adiabatic") are claims about dropped physics whose cross-domain entailments ("frictionless ⇒ no joint heating") form a web with no known complete calculus. De-risk: take ten real cross-domain analysis pairs and attempt their envelopes in the draft formalism; if half don't fit, rework the foundation before building.
2. **Proof of leverage** — the entire justification ("each iteration makes the next cheaper") is an empirical claim with zero evidence. De-risk: one vertical slice on a real, physically tested, brutally cross-coupled artifact — design, check, build, test, write back, tighten — and measure iteration 2 against iteration 1.
3. **Hash semantics** — tolerance-aware equivalence, solver nondeterminism, sensitivity-aware staleness (§4.3).
4. **Agent ergonomics** — nobody yet knows what makes a formalism good *for models*: context-window budgets for interface summaries, declarative constraints vs. executable tests, verbosity effects. Cheap to test; test before syntax ossifies.
5. **Governance** — conflicting parallel proposals over shared resources (the mass optimizer vs. the stiffness optimizer, fighting over one spar). Compile time detects the conflict; nothing yet decides it. Working hypothesis: analysis-as-argument (§3.1) is the substrate for resolution-by-recorded-reasoning rather than by authority — but this is a hope, not a design.
6. **The unmodeled** — the language enforces declared assumptions; it cannot discover undeclared ones, and the dominant cause of loss in complex systems is unsafe interaction among components that each meet spec. Mitigations, not solutions: aggressive perturbation testing at envelope boundaries, behavior-trace exploration, vision-agent review, and human ownership of specifications and seams. The green checkmark must never be sold as safety.

## 11. Roadmap

- **v0.1 (kernel proof):** text format + parser; units/dimensions; ports + conservation check; quantities with uncertainty and provenance; shell-and-core analysis nodes; content hashing + staleness over Git; Build123d geometry nodes with topological assertions; compile-time checker as a merge gate.
- **v0.2 (loop closure):** sensitivity-aware attention and experiment selection (the crude-first cut shipped post-v0.1 — ADR-0005: stale-set ranking, information value of candidate measurements, candidate entailment rules from discrepancies; v0.2 upgrades all three with derivative information) — ahead of transport and bridges, because the loop's scarce resources are agent attention and oracle contact, not plumbing; FMU transport; surrogate nodes; COTS datasheet ingestion; cost/lead-time rollups with distributor refresh; work-instruction projection with as-built write-back; SysML v2 import. (Runtime scheduler shipped in v0.1.)
- **v0.3 (calibration at scale):** envelope-tightening machinery with confidence history; discrepancy events; sensitivity-aware staleness; DFM ruleset library; SysML export for certification views.
- **Vertical slice throughout:** every version proves itself on one real cross-coupled vehicle, against the leverage metric (§10.2). The candidate testbed is small, fast to iterate, and unforgiving across aero, propulsion, structures, thermal, and RF.

---

*The platonic ideal is the direction of travel, never the claimed destination: a typed conservation graph whose assumption envelopes are continuously calibrated by the tests it generates — the substrate under a build-fly-learn loop, so that a thousand agents can share one reality, the dumb half of failures costs nothing, and every cycle of contact with the physical world makes the next one cheaper.*
