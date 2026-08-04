"""Usable servo bandwidth under the first structural mode (req PNT-003).

Loop shaping rule: position-loop crossover at f1/mode_margin_factor keeps
phase margin against a lightly damped locked-rotor resonance. The tracking
margin compares what the structure allows with what the L1 track demands
(~10x the highest significant apparent-motion content). This analysis
REQUIRES elastic_modes — the mode it shapes around must exist upstream.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}


def rel(block, name, default):
    unc = block[name].get("unc") or {}
    if unc.get("kind") == "rel":
        return float(unc.get("value", default))
    return default


f1 = I["f1"]                       # Hz
margin_factor = P["mode_margin_factor"]
f_need = P["required_tracking_bw"]  # Hz

bw = f1 / margin_factor                             # Hz
tracking_margin = bw / f_need                       # dimensionless

f1_rel = rel(p["inputs"], "f1", 0.12)
mf_rel = rel(p["params"], "mode_margin_factor", 0.10)
bw_rel = round(math.sqrt(f1_rel**2 + mf_rel**2), 2)

json.dump({
    "outputs": {
        "usable_bandwidth": {"value": round(bw, 3), "unit": "Hz",
                             "unc": {"kind": "rel", "value": bw_rel}},
        "tracking_margin": {"value": round(tracking_margin, 1), "unit": "",
                            "unc": {"kind": "rel", "value": bw_rel}},
    },
    "notes": f"crossover at f1/{margin_factor:g}; gust rejection, not target dynamics, sets the real need",
}, sys.stdout)
