# ground-station-lc — the same IMAP I-ALiRT capability at 1/10 the cost

A design excursion from [`../ground-station`](../ground-station): receive the
IMAP I-ALiRT X-band broadcast from L1 with ≥ 3 dB link margin — the identical
`MIS-001`/`LNK-002` requirements — for **$25.4k against a $26k cap** (baseline:
$224.8k). See [`TRADE.md`](TRADE.md) for the full trade study.

**The architecture:** two 3.0 m COTS VSAT dishes on consumer worm-drive
rotators, coherently combined through a shared-LO downconverter and a
two-channel SDR; steptrack on the I-ALiRT carrier itself for pointing; ballast
mounts with earth anchors instead of concrete.

**The result (lock values):** margin **3.34 dB** (vs 3 required), G/T 27.68
dB/K, pointing loss 0.205 dB of 0.30, 1.05 kW peak on a consumer circuit,
6-week critical path, $600 of cost margin. The price of the price: margin
luxury (5.38 → 3.34 dB), a 15 m/s full-track wind derate, and a
semi-consumable O&M posture — all declared in judgments, none hidden.

```sh
python3 -m uel check examples/ground-station-lc
python3 -m uel project all examples/ground-station-lc
```

Try: set `combining_loss_db` to `1 dB` in `model/design.uel` and watch the
margin walk to the floor through exactly the ArrayGain → GtArray → LinkMargin
cone — the design's one load-bearing software risk, made visible.
