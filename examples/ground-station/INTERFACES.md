# Ground-station interface contract — architect ⇄ engineering teams

*This document is the org-to-team boundary (program §7 discipline applied inward):
node names, output names, units, envelope fences, and file ownership are fixed
here. Teams fill in depth behind these names; nothing else crosses the boundary.
Deviations require flagging in your final report, not silent renaming.*

Read before writing a line: `docs/syntax.md`, `docs/core-protocol.md`,
`examples/apache-one/model/structure.uel` (the exemplar for style, judgments,
provenance tails), `uel/stdlib/*.uel` (materials, claims, DFM rulesets).

## File ownership (create ONLY your files; never edit skeleton or other teams')

| Team | Model file | Cores (create under examples/ground-station/) |
|---|---|---|
| RF | `model/rf.uel` | `analysis/antenna_gain.py`, `analysis/system_noise.py`, `analysis/gt_analysis.py`, `analysis/link_margin.py` |
| Structures | `model/structures.uel` | `geom/reflector_geom.py`, `geom/counterweight_bracket.py`, `analysis/wind_loads.py`, `analysis/pedestal_modes.py`, `analysis/servo_sizing.py`, `analysis/servo_bandwidth.py`, `analysis/pointing_budget.py` |
| Facilities | `model/facilities.uel` | `analysis/power_budget.py`, `analysis/enclosure_thermal.py`, `analysis/ups_ride_through.py` |

Architect owns: `model/requirements.uel`, `model/station.uel`, `lib/`, `uel.toml`,
`stubs/`. All functional components, ports, and connects already exist in
`model/station.uel` — bind realizations to them; do not add connects.

## Conventions

- dB is a dimensionless ratio label (`margin_db = 3 dB`); absolute log levels
  carry the reference in the NAME (`eirp_dbw`, `cn0_dbhz`) — see docs/syntax.md.
- Every binding declares `mass`, `unit_cost` (with `from "vendor/quote"` tails),
  and `lead_time` — the rollups and budgets close only if you do.
- Every analysis: `intent` a requirement, framing with `assume … because "…"`,
  honest `judgment … doubts "…"`, outputs with `±` where uncertain.
- Cores: Python stdlib only, deterministic, JSON stdin→stdout per
  docs/core-protocol.md; geometry cores MUST return topological assertions.

## Cross-team edges (the seams; exact refs)

| Consumer (team) | known ← ref | Producer (team) |
|---|---|---|
| `LinkMargin` (RF) | `pointing_loss_db <- PointingBudget.outputs.pointing_loss_db` | Structures |
| `SystemNoise` (RF) | `lna_physical_temp <- EnclosureThermal.outputs.lna_physical_temp` | Facilities |
| `PointingBudget` (Structures) | `hpbw <- AntennaGain.outputs.hpbw` | RF |
| `PowerBudget` (Facilities) | `peak_drive_power <- ServoSizing.outputs.peak_drive_power` | Structures |

Envelope fences at the seams (write exactly these):
- `EnclosureThermal` guarantees `lna_physical_temp in [-5, 40] degC`;
  `SystemNoise` assumes `lna_physical_temp in [0, 35] degC` (⊆ guarantee).
- `ServoBandwidth` framing: `require elastic_modes because "loop shaping needs the first structural mode"`;
  `PedestalModes` framing: `assume elastic_modes because "modal content is the product"`.

## Deliverables — RF team (`model/rf.uel`)

Bindings (datasheet pattern, spec §7.2; invent plausible part IDs, vendor-prov quantities):
- `FeedAssembly -> feed_x84` : `insertion_loss_db = 0.3 dB ± 0.05 dB`, mass ≈ 6 kg, ≈ 12000 USD, 10 week.
- `Lna -> lna_x40k` : `noise_temperature = 45 K ± 15 %` (vendor), `gain_db = 40 dB`, ≈ 4500 USD, 6 week. Datasheet operating fence `T in [-40, 60] degC`.
- `Downconverter -> dc_x2l_v2` (≈ 6000 USD), `SdrReceiver -> sdr_x310` (≈ 8000 USD), `RefOscillator -> gpsdo_10m` (≈ 2200 USD).

Analyses (names/outputs fixed):
1. **AntennaGain** — intent `req.LNK-002`. knowns: `freq <- req.MIS-001.carrier_freq`,
   `diameter <- Reflector.aperture_diameter`, `efficiency <- Reflector.aperture_efficiency`,
   `surface_rms <- Reflector.surface_rms_spec`. Physics: G = 10log10(η(πD/λ)²) −
   Ruze 4.343·(4πε/λ)²; HPBW = 70λ/D deg. outputs: `gain_dbi : dB ±`, `hpbw : deg`.
   (Nominal ≈ 50.65 dBi, 0.497°.)
2. **SystemNoise** — intent `req.LNK-002`. knowns: `lna_noise_temp <- lna_x40k.noise_temperature`,
   `feed_loss_db <- feed_x84.insertion_loss_db`, `lna_physical_temp <- EnclosureThermal.outputs.lna_physical_temp`,
   `min_elevation <- req.ENV-004.min_elevation`. params: sky/spillover temps with rationale.
   T_sys = T_ant + T_feedloss + T_lna(+small drift with physical temp) + T_downstream.
   outputs: `t_sys : K ±`. Envelope: `lna_physical_temp in [0, 35] degC`. (Nominal ≈ 124 K.)
3. **GtAnalysis** — intent `req.LNK-002`. knowns: `gain_dbi <- AntennaGain.outputs.gain_dbi`,
   `t_sys <- SystemNoise.outputs.t_sys`, `feed_loss_db <- feed_x84.insertion_loss_db`.
   G/T = gain − feed_loss − 10log10(T_sys), referenced at LNA input.
   outputs: `g_over_t_dbk : dB ±`. (Nominal ≈ 29.4.)
4. **LinkMargin** — intent `req.LNK-002`. knowns: all of req.LNK-002's quantities,
   `freq <- req.MIS-001.carrier_freq`, `data_rate <- req.MIS-001.data_rate`,
   `g_over_t_dbk <- GtAnalysis.outputs.g_over_t_dbk`,
   `pointing_loss_db <- PointingBudget.outputs.pointing_loss_db`.
   C/N0 = EIRP − FSPL − atm − rain − pol − pointing + G/T + 228.6;
   Eb/N0 = C/N0 − 10log10(rate); margin = Eb/N0 − (required + impl).
   outputs: `cn0_dbhz : dB ±`, `ebn0_db : dB ±`, `margin_db : dB ±`.
   Envelope: `eirp_dbw in [18, 26] dB`. (Nominal margin ≈ 5.3 dB ≥ 3 required.)

## Deliverables — Structures team (`model/structures.uel`)

Bindings:
- `Reflector -> reflector_v1` : `geometry reflector_geom`, ≈ 48000 USD quote, 18 week.
- `Pedestal -> pedestal_ae5` : vendor az-el positioner; `mass ≈ 2100 kg`,
  `locked_rotor_stiffness = 85 MN*m ± 20 %` (torque per radian; rad is dimensionless),
  ≈ 95000 USD, 20 week. Envelope `T in [-40, 55] degC`.
- `CounterweightSet -> counterweight_v1` : `geometry counterweight_bracket_geom`,
  process `cnc_3axis`, material AL6061_T6 for the bracket; declare total set mass
  ≈ 620 kg (steel masses as quantities), ≈ 6000 USD.

Geometry cores:
- `reflector_geom` (params: knowns from `Reflector.aperture_diameter`, `Reflector.focal_ratio`;
  areal-density param with rationale): outputs `mass : kg ±`, `aperture_area : m^2`,
  `frontal_area : m^2`, `focal_length : m`. Assertions: paraboloid closes, f/D in [0.3, 0.5].
- `counterweight_bracket_geom`: a real machined part — outputs mass/volume, features
  for the cnc_3axis DFM ruleset (`min_internal_radius`, `min_wall_thickness`,
  `sharp_internal_corner_count`, `loaded_internal_corner_min_fillet`,
  `undeclared_undercut_count`), passing values, plus topological assertions.

Analyses:
1. **WindLoads** — intent `req.ENV-004`. knowns: `wind_op <- req.ENV-004.wind_operational`,
   `wind_survival <- req.ENV-004.wind_survival`, `frontal_area <- reflector_v1.frontal_area`.
   params: Cd ≈ 1.3 face-on, gust factor 1.6, stow drag reduction, moment arm.
   outputs: `drag_force : kN ±`, `overturning_moment : kN*m ±`, `survival_moment : kN*m ±`.
   Envelope: `wind_op in [0, 50] m/s`.
2. **PedestalModes** — intent `req.PNT-003`. knowns: `stiffness <- pedestal_ae5.locked_rotor_stiffness`,
   dish mass+arm (inertia) from `reflector_v1.mass` + params. f1 = (1/2π)√(k/J).
   framing: `assume elastic_modes because "modal content is the product"`, linear_elastic.
   outputs: `first_locked_rotor_mode : Hz ±`. (Nominal ≈ 4–6 Hz.)
3. **ServoSizing** — intent `req.ENV-004`. knowns: `overturning_moment <- WindLoads.outputs.overturning_moment`,
   `track_rate <- req.PNT-003.track_rate_max`. outputs: `peak_torque : kN*m ±`,
   `peak_drive_power : W ±`. (Nominal peak power ≈ 2200 W.)
4. **ServoBandwidth** — intent `req.PNT-003`. knowns: `f1 <- PedestalModes.outputs.first_locked_rotor_mode`.
   framing: `require elastic_modes because "loop shaping needs the first structural mode"`.
   Usable bw ≈ f1/3; tracking needs ≈ 10× track-rate crossover.
   outputs: `usable_bandwidth : Hz ±`, `tracking_margin : dimensionless ±`.
5. **PointingBudget** — intent `req.PNT-003`. knowns: `hpbw <- AntennaGain.outputs.hpbw`,
   `gust_moment <- WindLoads.outputs.overturning_moment`, `stiffness <- pedestal_ae5.locked_rotor_stiffness`,
   `max_err <- req.PNT-003.max_pointing_error`. params: servo/encoder/ephemeris/thermal
   error terms with rationale. RSS the terms; loss_db = 12·(θ/HPBW)².
   outputs: `total_pointing_error : deg ±`, `pointing_loss_db : dB ±`.
   (Nominal ≈ 0.035°, ≈ 0.06 dB.)

## Deliverables — Facilities team (`model/facilities.uel`)

Bindings:
- `PowerDistribution -> pdist_v1` (≈ 9000 USD, ≈ 120 kg), `UpsUnit -> ups_2200`
  (vendor: `energy_capacity = 0.9 kW*hr ± 10 %`, ≈ 1400 USD, ≈ 28 kg),
  `LnaEnclosure -> lna_enclosure_v1` (`heater_power = 800 W`, ≈ 3500 USD, ≈ 22 kg),
  `StationServer -> server_r1` (`continuous_draw = 450 W ± 10 %` incl. SDR host, ≈ 4200 USD),
  `SiteWorks -> site_works_v1` (`mass = 0 kg` by convention — see skeleton doc, ≈ 25000 USD, 8 week).

Analyses:
1. **PowerBudget** — intent `req.PWR-005`. knowns: `peak_drive_power <- ServoSizing.outputs.peak_drive_power`,
   `heater_power <- lna_enclosure_v1.heater_power`, `server_draw <- server_r1.continuous_draw`,
   `max_feed <- req.PWR-005.max_feed_power`. params: RF chain DC (≈ 60 W), dehydrator,
   margin policy. outputs: `total_continuous_draw : W ±`, `peak_draw : W ±`,
   `supply_margin : W ±`. (Peak ≈ 4 kW ≤ 8 kW.)
2. **EnclosureThermal** — intent `req.ENV-004`. knowns: `t_amb_min <- req.ENV-004.t_amb_min`,
   `t_amb_max <- req.ENV-004.t_amb_max`, `heater_power <- lna_enclosure_v1.heater_power`.
   params: enclosure UA (W/K), internal dissipation, with rationale. framing:
   `assume lumped_element`, `assume steady_state`. Envelope guarantee:
   `lna_physical_temp in [-5, 40] degC` AND `T_amb in [-30, 45] degC`.
   outputs: `lna_physical_temp : degC ±` (report the hot-case value),
   `heater_duty : dimensionless ±` (cold case). (Nominal hot ≈ 25–35 degC.)
3. **UpsRideThrough** — intent `req.PWR-005`. knowns: `capacity <- ups_2200.energy_capacity`,
   `server_draw <- server_r1.continuous_draw`, `min_ride <- req.PWR-005.min_ride_through`.
   params: inverter efficiency, chain DC load. outputs: `ride_through_time : min ±`.
   (Nominal ≈ 60–90 min ≥ 10.)

## Self-verification (required before you report done)

Work in the real tree (your files only). Other teams work concurrently — the
shared-tree check may show THEIR unresolved names; that noise is not yours.
Your acceptance is the ISOLATED check:

```sh
cd /home/user/unified-engineering-language
ISO=/tmp/claude-0/-home-user-unified-engineering-language/92205e77-6231-5aed-9c58-da1869b38e24/scratchpad/iso-<team>
rm -rf $ISO && mkdir -p $ISO/model $ISO/lib $ISO/analysis $ISO/geom
cp examples/ground-station/uel.toml $ISO/
cp examples/ground-station/lib/domains.uel $ISO/lib/
cp examples/ground-station/model/requirements.uel examples/ground-station/model/station.uel $ISO/model/
cp examples/ground-station/stubs/<other-team>.uel ... $ISO/model/     # stubs for teams that are NOT you
cp examples/ground-station/stubs/cores/*.py $ISO/analysis/            # stub cores
cp <your model file> $ISO/model/ ; cp <your cores> $ISO/analysis/ (and $ISO/geom/)
python3 -m uel check $ISO     # zero errors (warnings/infos acceptable and expected)
python3 -m uel build $ISO     # all YOUR cores run; zero failed
python3 -m uel check $ISO     # still zero errors (DFM now sees geometry features)
```

Do not run `git` commands. Report: files created, key computed values
(vs the nominals above), and any deviation from this contract.
