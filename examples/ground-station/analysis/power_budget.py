"""Station power ledger against the single utility feed (req PWR-005).

base            = server + RF-chain DC + dehydrator + misc          (steady, non-heater)
continuous      = base + heater_power * heater_duty_avg             (duty-weighted heater)
peak            = base + full heater + servo peak drive             (cold, tracking in wind)
supply_margin   = max_feed - peak * (1 + growth_allowance)          (program margin policy)

All quantities arrive SI (W) in the `si` field. Uncertainties: every declared
band in this model is relative, so terms propagate as RSS of absolute sigmas;
quantities without a declared band contribute zero.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = p["inputs"]
P = p["params"]


def si(e):
    return e["si"]


def sigma(e):
    """Absolute SI sigma from a declared relative band; 0 when undeclared."""
    u = e.get("unc")
    if not u or u.get("kind") != "rel":
        return 0.0
    return abs(si(e)) * float(u.get("value", 0.0))


def rss(*xs):
    return math.sqrt(sum(x * x for x in xs))


server = si(I["server_draw"])          # W
heater = si(I["heater_power"])         # W
drive = si(I["peak_drive_power"])      # W
max_feed = si(I["max_feed"])           # W
chain = si(P["rf_chain_dc"])           # W
dehyd = si(P["dehydrator_draw"])       # W
misc = si(P["misc_draw"])              # W
duty = si(P["heater_duty_avg"])        # -
growth = si(P["growth_allowance"])     # -

base = server + chain + dehyd + misc
total_continuous = base + heater * duty
peak = base + heater + drive
margin = max_feed - peak * (1.0 + growth)

s_base = rss(sigma(I["server_draw"]), sigma(P["rf_chain_dc"]),
             sigma(P["dehydrator_draw"]), sigma(P["misc_draw"]))
s_cont = rss(s_base, sigma(I["heater_power"]) * duty)
s_peak = rss(s_base, sigma(I["heater_power"]), sigma(I["peak_drive_power"]))
s_margin = s_peak * (1.0 + growth)

json.dump({
    "outputs": {
        "total_continuous_draw": {"value": round(total_continuous, 1), "unit": "W",
                                  "unc": {"kind": "abs", "value": round(s_cont, 1)}},
        "peak_draw": {"value": round(peak, 1), "unit": "W",
                      "unc": {"kind": "abs", "value": round(s_peak, 1)}},
        "supply_margin": {"value": round(margin, 1), "unit": "W",
                          "unc": {"kind": "abs", "value": round(s_margin, 1)}},
    },
    "notes": "margin quoted after the growth_allowance policy on peak; "
             "raw feed headroom is max_feed - peak",
}, sys.stdout)
