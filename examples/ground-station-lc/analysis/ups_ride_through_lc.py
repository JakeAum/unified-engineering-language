"""Consumer UPS ride-through at end of life."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}
load = I["server_draw"] + I["chain_dc_draw"]
ride = I["capacity"] * P["eta_inv"] * P["eol_derate"] / load
u = math.sqrt(0.1 ** 2 + 0.05 ** 2 + 0.1 ** 2)
json.dump({"outputs": {"ride_through_time": {"value": round(ride / 60.0, 2), "unit": "min",
                                              "unc": {"kind": "rel", "value": round(u, 3)}}}},
          sys.stdout)
