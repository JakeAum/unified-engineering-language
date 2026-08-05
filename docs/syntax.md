# UEL surface syntax — v0.2 reference

*The customer is an AI agent (spec §5.1): plain text, line-oriented, diff-friendly,
locally checkable, explicit over implicit. This document is the normative reference
for the v0.2 grammar; `uel fmt` is the normative layout.*

## Lexical rules

- UTF-8. Comments: `#` to end of line. Newlines, `;` and `,` are interchangeable
  separators; the formatter emits one declaration per line.
- All keywords are **contextual** — nothing is reserved; `flow`, `model`, `text`
  remain valid names everywhere else.
- Identifiers may contain internal hyphens between alphanumerics (`STR-014`).
  Inside v0.2 expression bodies, subtraction therefore needs spaces (`a - b`);
  the checker recognizes `a-b` and suggests the fix.
- `±` may be typed `+-`. Strings are double-quoted with `\n \t \" \\`.
- Paths (core scripts, datasheets) are quoted strings.

## Quantities

```
240 g               # scalar with unit
240 g ± 10 g        # absolute uncertainty (unit may differ in scale: ± 10 mg)
503 MPa ± 3 %       # relative uncertainty
[0, 12 kN]          # interval; unit inside the bracket applies to both bounds
[0, 12] kN          # accepted; formatter moves the unit inside
[0, 12 kN] ± cal    # calibration-pending uncertainty: declared, not yet known
1.5                 # dimensionless
85 USD              # currency is a base dimension; cost flows through the graph
```

Unit expressions: `kN`, `kg/m^3`, `N*m`, `mm^4`, `kg/(m*s^2)`, `W/K`, `A*hr`.
SI prefixes n µ m c d k M G T on prefixable symbols. Affine units (`degC`, `degF`)
are standalone-only. Angle is dimensionless (`rad` = 1, `deg` = π/180), so
torque `N*m` × speed `rad/s` = power.

**Levels (v0.2, ADR-0006).** The dB family are *level units*: a level's type is
the referenced linear dimension plus a level flag, and its canonical scale is
dB re the SI-coherent unit. `dB` is the level of a pure ratio (gains, losses,
margins); `dBi`, `dBW`, `dBm` (−30 to canonical), `dBHz`, `dBK` are named
references; composition shifts the reference (`dB/K`, `dBW/(K*Hz)`). EIRP is
`22 dBW`, not "22 dB with the reference in the name". Uncertainty on a level is
a dB delta: `22 dBW ± 1.5 dB`. Two levels cannot compose as units, a level
takes no exponent, and nothing divides *by* a level.

## Top-level items

### requirement

```
requirement STR-014 {
  text "carry limit load, FoS >= 1.5"
  limit_load = 12 kN
  min_FoS = 1.5
}
```

Referenced as `req.STR-014`, quantities as `req.STR-014.limit_load`.

### component

```
component MainSpar : functional {        # levels: functional | behavioral | physical
  doc "Primary wing bending member"
  port root_attach : mechanical.translation {
    direction inout                      # in | out | inout (default)
    force: [0, 12 kN] ± cal              # port attrs use ':' (typed slots)
    voltage: [8, 26 V] from "p.2"        # attrs take provenance tails too
  }
  mass_margin = 0.15                     # quantities use '='
  budget mass <= 240 g ± 10 g            # typed rollups: mass, unit_cost, lead_time
  budget unit_cost <= 85 USD @ qty 25
  contains RibSet x 6                    # assembly tree (drives rollups)
  envelope {
    T in [-40, 70] degC                  # value predicates fence validity
    Mach <= 0.3                          # one-sided bounds
    assume lumped_element because "gradients unresolved"
    require elastic_modes because "downstream flutter needs modes"
  }
}
```

Port domains come from the domain table (`lib.domains.*` or project-declared).
Port attributes named after the domain's effort/flow (or `power`) are
dimension-checked against the domain.

### binding

```
binding MainSpar -> spar_v7 : physical {
  process cnc_3axis                      # activates that process's DFM ruleset
  material AL7075_T6 from lib.materials  # or: material lib.materials.AL7075_T6
  geometry spar_v7_geom                  # reference an explicit geometry node…
  # geometry code "geom/spar_v7.py"      # …or sugar: creates spar_v7_geom with
                                         #    params = this binding's quantities
  datasheet "vendor/tps62130.pdf" sha256 "9a41…"   # COTS pattern (spec §7.2)
  length = 850 mm
  envelope { T in [-40, 125] degC }      # e.g. datasheet absolute-max fence
}
```

A binding produces a **physical component node** named `spar_v7` with
`realizes MainSpar`. Member lookups on it fall through to its geometry node's
outputs: `spar_v7.section_Ixx` resolves to `spar_v7_geom.outputs.section_Ixx`.

### geometry and analysis (the shell, spec §3.2)

```
geometry spar_v7_geom {
  core python "geom/spar_v7.py"          # opaque core; content-hashed
  params { outer_diameter = 22 mm  wall = 1.6 mm  length = 850 mm }
  knowns { density <- lib.materials.AL7075_T6.density }
  outputs {
    mass : g ±                           # trailing ± = carries uncertainty
    section_Ixx : mm^4
    mesh : artifact                      # file artifact, not a quantity
  }
}

analysis SparStaticLimit {
  intent req.STR-014 "will the spar carry limit load at Mach 1 pull-up?"
  framing {
    model beam.euler_bernoulli
    assume rigid_root because "root fitting stiffness >> spar; see AN-009"
    assume static because "gust transient covered by SparDynamic"
    envelope { load in [0, 18 kN], T in [-40, 70] degC }
  }
  knowns {
    load <- req.STR-014.limit_load       # references, never copies
    section_Ixx <- spar_v7.section_Ixx
    yield_strength <- lib.materials.AL7075_T6.yield_strength
  }
  core python "analysis/spar_static.py"
  outputs { FoS : dimensionless ± ; max_deflection : mm ± }
  judgment pending
  # judgment accepted "physical, converged" doubts "root stiffness unverified"
}
```

Analysis outputs are addressed with an explicit segment: `SparStaticLimit.outputs.FoS`.

### expression and stub cores (v0.2, ADR-0005/0006/0007)

The formula itself may live in the language. The checker infers every
expression's type — dimension **plus level flag** — before anything runs, and
evaluation is kernel-side interval arithmetic over the knowns' declared bands:

```
analysis LinkMargin {
  knowns {
    eirp_dbw <- req.LNK-002.eirp_dbw     # 22 dBW ± cal — a level of power
    freq <- req.MIS-001.carrier_freq
    max_range <- req.LNK-002.max_range
    data_rate <- req.MIS-001.data_rate
    g_over_t_dbk <- GtAnalysis.outputs.g_over_t_dbk
    required_ebn0_db <- req.LNK-002.required_ebn0_db
  }
  core expr {
    let lambda = const.c0 / freq
    let fspl_db = 2 * db(4 * const.pi * max_range / lambda)
    cn0_dbhz = eirp_dbw - fspl_db + g_over_t_dbk - db(const.k_B)
    margin_db = cn0_dbhz - db(data_rate) - required_ebn0_db
  }
  outputs {
    cn0_dbhz : dBHz ±                     # the dBHz is DERIVED by the checker
    margin_db : dB ± target >= req.LNK-002.min_margin_db
  }
}

analysis GtStub {
  core stub { g_over_t_dbk = 29.6 dB/K }  # executable placeholder, ledgered
  outputs { g_over_t_dbk : dB/K }
}
```

- Statements are `let name = expr` (intermediate) or `output = expr`; each
  declared output is assigned exactly once, in order; later statements may
  consume earlier outputs. Statements end at newline; a line continues after a
  binary operator or inside parentheses.
- Operators `+ - * / ^` (integer exponents); functions `sqrt log10 ln exp sin
  cos abs min max db lin`; constants `const.pi c0 k_B h g0`.
- Numeric literals take units greedily but *validated*: `3 m / span` divides
  `(3 m)` by the name `span`, because `span` is not a unit symbol. The
  formatter parenthesizes united literals under `*`, `/`, and `^`.
- Levels (`dB`, `dBi`, `dBW`, `dBm`, `dBHz`, `dBK`, `dB/K`, …) follow one
  rule: **levels add where linear quantities multiply** — `Level(D1) ±
  Level(D2) = Level(D1·D2 or D1/D2)`, `db()`/`lin()` cross the scales, and a
  scalar multiplies only a plain `dB` figure. Uncertainty on a level is a dB
  delta (`± 1.5 dB`).
- `target >= bound` / `target <= bound` on an output (literal or reference) is
  re-verdicted against the lock on every build and check: violated = error,
  band-crosses-the-line = warning, unbuilt = pending.
- Identifiers may contain hyphens (`STR-014`), so **subtraction needs
  spaces**: `a - b`. The checker recognizes `a-b` and says so.
- Geometry nodes cannot be expr/stub cores — they must assert topology.

### connect

```
connect battery.main_out -> esc.dc_in
```

Endpoints are `component.port`; domains must match; conservation checks run at
compile time (Phase 4).

### Library items — domain, claim, material, process

Declared in `lib/*.uel` (project) or shipped in the stdlib; namespaced by file
stem: `lib/domains.uel` → `lib.domains.*`. See `uel/stdlib/*.uel` for the shipped
set — the domain table, the structural-claim taxonomy with entailments, materials,
and DFM process rulesets.

```
domain thermal { class power  effort temperature: K  flow entropy_flow: W/K }
claim rigid { entails no_elastic_modes  excludes elastic_modes }
material AL7075_T6 { density = 2810 kg/m^3  E = 71.7 GPa }
process cnc_3axis {
  rule min_internal_radius: min_internal_radius >= 2 mm
    "the cutter must sweep, not dwell"
  rule no_sharp_internal_corners: forbid sharp_internal_corner_count
    "impossible on a rotating cutter"
}
```

## Projects

```
uel.toml          # [project] name/edition/model dirs; [tolerances] hash grids
model/*.uel       # the graph
lib/*.uel         # project libraries (lib.<stem>.*)
uel.lock          # recorded hashes + outputs (written by `uel build`)
```

## Restrictions (deliberate)

- Arithmetic lives only inside `core expr` bodies (v0.2). Declared quantities
  remain literals, and derived values remain analysis outputs — that is what
  keeps staleness honest.
- Quantities cannot be reference-valued; references live in `knowns` (and in
  output `target` bounds).
- One namespace per project; no imports. Libraries are namespaced by file.
- Expression bodies have no conditionals, loops, or fractional powers of
  dimensioned quantities; a core that needs them is a Python core.
