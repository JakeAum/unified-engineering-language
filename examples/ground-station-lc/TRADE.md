# Trade study: the same capability at one tenth the cost

*Excursion from `examples/ground-station` (baseline, $224.8k against a $260k
cap) to a $26k cap. Method: copy the requirements, keep MIS-001 and LNK-002
verbatim (capability is not negotiable), set `CST-006.cost_cap = 26000 USD`,
and redesign until the merge gate goes green. Both graphs are in the repo;
every number below is a lock value, not a slide number.*

## Where the money was, and where it went

| Item | Baseline | Excursion | The move |
|---|---|---|---|
| Aperture | 5 m custom reflector, $48k | 2× 3.0 m COTS VSAT dish, $7.6k | **Array + DSP instead of aperture**: coherent combining buys +3.0 dB back of the 4.4 dB a single 3 m gives up |
| Pointing | Industrial az-el positioner, $95k | 2× worm-drive rotator, $3.4k | **Software instead of steel**: steptrack on the I-ALiRT carrier itself holds 0.11° on a 0.83° beam — 0.20 dB of the 0.30 allocation |
| Site | Engineered foundation, $25k | Ballast blocks + earth anchors, $2.6k | 3 m elements don't need concrete; survival moment reacts through anchors |
| Feed/LNA | $16.5k precision chain | $2.6k catalog modules | 10 K of T_sys given up, bought back by the array factor |
| Back end | $21k | $6.6k (shared-LO 2-ch downconverter + coherent SDR) | One LO = phase coherence by construction |
| Facilities | $18.1k | $2.7k consumer-grade | The tenth-cost station is also a fifth of the power (1.05 kW peak) |
| **Total** | **$224.8k** | **$25.4k (9.1%)** | |

## What the capability costs at a tenth the price

| Metric | Baseline | Excursion | Verdict |
|---|---|---|---|
| Link margin at max range | 5.38 dB | **3.34 dB** | both ≥ 3 required — but the excursion has essentially zero luxury |
| G/T | 29.59 dB/K | 27.68 dB/K | −1.9 dB, the honest price of COTS |
| Pointing loss | 0.074 dB | 0.205 dB | both inside the 0.30 allocation |
| Full-spec tracking wind | 20 m/s | **15 m/s** (hold to 20, stow above) | declared availability derate — consumer rotators |
| Power, peak | 5.27 kW | 1.05 kW | excursion better |
| Lead time | 20 weeks | 6 weeks | excursion better |
| Fault tolerance | single aperture | graceful: one element down → margin ≈ 0.6 dB **(below floor — degraded, not dead: frames still decode in clear sky at mid-elevations)** | different failure shape |
| Growth path | none priced | `n_elements` fenced to 4: two more elements ≈ +$15k → +2.7 dB margin | the recovery plan if combining loss disappoints |

## What is genuinely thinner (declared, not hidden)

1. **Margin lives one surprise from the floor.** Combining loss is carried at
   0.3 ± 50 % dB — a software-quality number no datasheet backs. If first
   light measures 1 dB, margin is 2.6 and the station fails its requirement
   until a third element ships. That is the design's single biggest doubt and
   it is written in `ArrayGain`'s judgment.
2. **Wind availability.** Full-spec tracking derates to 15 m/s; between 15
   and 20 the rotators hold position on ephemeris feed-forward with degraded
   pointing; above 20 the elements stow. At a temperate site this is a
   ~1–2 %-of-hours availability haircut concentrated in storms.
3. **O&M posture.** Consumer parts fail more often; the answer is spares in
   the box (the site kit carries them) and graceful array degradation, not
   MTBF. The station is semi-consumable by design.
4. **No DFM'd custom structure at all** — nothing in this design deserves a
   machine shop. The one "custom" item (septum feed) is a small-shop batch
   part priced as a quote.

## How the graph earned its keep

Setting `cost_cap` to a tenth did not produce an argument; it produced a work
list: the budget rollup errors named exactly which groups were impossible under
the old architecture, the link-margin chain said precisely how many dB the
smaller aperture had to find (array factor + accepted-margin spend), and the
baseline's LinkMargin **expr formula is reused verbatim** against the new
producers — the two projects' `core expr` bodies are character-identical, so
their content hashes prove it is the same capability question, the same
physics, and a different design answering it. Since v0.2 the margin floor is a
declared output target, and the checker adds what this table cannot: the
worst-case band on the excursion's margin crosses the 3 dB line — a standing
warning on every check, which is this design's thinness made mechanical.
