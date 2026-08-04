# UEL surface syntax — v0.1 reference

*The customer is an AI agent (spec §5.1): plain text, line-oriented, diff-friendly,
locally checkable, explicit over implicit. This document is the normative reference
for the v0.1 grammar; `uel fmt` is the normative layout.*

## Lexical rules

- UTF-8. Comments: `#` to end of line. Newlines, `;` and `,` are interchangeable
  separators; the formatter emits one declaration per line.
- All keywords are **contextual** — nothing is reserved; `flow`, `model`, `text`
  remain valid names everywhere else.
- Identifiers may contain internal hyphens between alphanumerics (`STR-014`).
  There is no arithmetic in v0.1, so no ambiguity with minus.
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
torque `N*m` × speed `rad/s` = power. `dB` is a dimensionless *ratio label*
(gains, losses, margins) carried on the dB scale; absolute log-referenced levels
are not units — carry the reference in the name (`eirp_dbw = 22 dB`,
`cn0_dbhz`).

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

## v0.1 restrictions (deliberate)

- No arithmetic expressions; quantities are literals. Derived values are analysis
  outputs — that is what keeps staleness honest.
- Quantities cannot be reference-valued; references live in `knowns`.
- One namespace per project; no imports. Libraries are namespaced by file.
