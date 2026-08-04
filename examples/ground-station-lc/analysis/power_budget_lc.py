"""Consumer-circuit power ledger for the two-element station."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

base = I["server_draw"] + I["chain_dc_draw"] + P["misc_draw"]
cont = base + P["heater_power"] * P["heater_duty_avg"]
peak = base + P["heater_power"] + P["rotator_peak"]
margin = I["max_feed"] - peak

u = math.sqrt((0.1 * I["server_draw"]) ** 2 + (0.2 * P["rotator_peak"]) ** 2
              + (0.3 * P["misc_draw"]) ** 2 + (0.1 * P["heater_power"]) ** 2)
json.dump({"outputs": {
    "total_continuous_draw": {"value": round(cont, 1), "unit": "W",
                              "unc": {"kind": "abs", "value": round(u * 0.7, 1)}},
    "peak_draw": {"value": round(peak, 1), "unit": "W",
                  "unc": {"kind": "abs", "value": round(u, 1)}},
    "supply_margin": {"value": round(margin, 1), "unit": "W",
                      "unc": {"kind": "abs", "value": round(u, 1)}},
}}, sys.stdout)
