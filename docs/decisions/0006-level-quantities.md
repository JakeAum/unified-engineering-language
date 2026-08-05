# ADR-0006 — Level quantities: dB carries its reference in the type

*Status: accepted · v0.2 · 2026-08-05 · amends spec §2.4 (units) and the v0.1 dB rule*

## Intent

v0.1 declared `dB` a dimensionless ratio label and pushed every absolute
log-referenced level into naming convention: `eirp_dbw`, `cn0_dbhz`. The
RF-heavy ground station then spent its whole life in the units checker's blind
spot — the checker that was the star everywhere else. The retrospective called
this the clearest falsifiable miss.

## Decision

A **level** is `10·log10` of a linear quantity against an SI-coherent
reference. Its *type* is (referenced dimension, level flag); its canonical
scale is "dB re the SI-coherent unit".

- **Named level units**: `dB` (= level of a pure ratio), `dBi`, `dBW`, `dBm`
  (additive −30 to canonical), `dBHz`, `dBK`.
- **Unit composition**: a level composed with a linear unit shifts the
  reference — `dB/K` ≡ level of 1/K, `dBW/(K*Hz)` ≡ level of W/(K·Hz),
  `dBW/kHz` ≡ canonical −30. Two levels composed, a level raised to a power,
  or division *by* a level have no affine-map meaning and are unit errors.
- **The one arithmetic rule** (expression layer): *levels add where linear
  quantities multiply* —

      Level(D1) + Level(D2) = Level(D1·D2)
      Level(D1) − Level(D2) = Level(D1/D2)      dB = Level(1)

  `db(x)` lifts linear → level; `lin(x)` drops back. A scalar multiplies only
  a plain `dB` figure (the 20·log10 and array-factor idiom); scaling any other
  level is an error with the fix in the message.
- **Uncertainty on a level is a dB delta** (a difference of levels of one
  reference *is* a ratio): `22 dBW ± 1.5 dB` is well-typed; `± 3 K` on a level
  is not.
- **Hashing** normalizes levels like everything else: `52 dBm` and `22 dBW`
  are the same content; tolerance grids may be declared per level type
  (`"0.001 dB"`).

## Consequences

- The link budget's bookkeeping is now *derived, not asserted*: in the
  ground-station LinkMargin, `dBW − dB + dB/K − db(J/K)` type-checks to
  `dBHz`, and `Level(Hz) − Level(Hz)` to `dB` — the checker computes what
  C/N0 and Eb/N0 are.
- Requirements state EIRP as `22 dBW`, G/T as `dB/K`; the names lost their
  smuggled semantics.
- Field-quantity (20·log10) levels are not special-cased: square the linear
  quantity first, or scale a `dB` figure — both spellings are checked.

## Revisit

If nepers, dBFS, or per-bandwidth spectral conventions (dBm/Hz vs dBm per
channel) arrive, they must come as unit-table entries with explicit
references, never as naming convention again.
