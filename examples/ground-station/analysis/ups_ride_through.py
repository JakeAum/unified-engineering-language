"""UPS ride-through for the protected bus (req PWR-005), reservoir discharge.

    ride = capacity * eta_inv * eol_derate / (server_draw + chain_dc_draw)

Energy arrives SI (J), loads in W; ride is returned in seconds and the shell
normalizes into the declared minutes. Sized at end-of-life battery capacity.
Uncertainty: RSS of the declared relative bands on capacity, efficiency, and
the two loads (loads enter at minus-first order; relative sigmas add in RSS).
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = p["inputs"]
P = p["params"]


def si(e):
    return e["si"]


def rel(e):
    u = e.get("unc")
    if not u or u.get("kind") != "rel":
        return 0.0
    return float(u.get("value", 0.0))


capacity = si(I["capacity"])          # J
server = si(I["server_draw"])         # W
min_ride = si(I["min_ride"])          # s (10 min floor; carried for the record)
eta = si(P["eta_inv"])                # -
chain = si(P["chain_dc_draw"])        # W
eol = si(P["eol_derate"])             # -

load = server + chain                                        # W
ride = capacity * eta * eol / load                           # s

# load sigma in W -> relative on the quotient
s_load_rel = math.sqrt((rel(I["server_draw"]) * server) ** 2
                       + (rel(P["chain_dc_draw"]) * chain) ** 2) / load
s_rel = math.sqrt(rel(I["capacity"]) ** 2 + rel(P["eta_inv"]) ** 2
                  + rel(P["eol_derate"]) ** 2 + s_load_rel ** 2)

json.dump({
    "outputs": {
        "ride_through_time": {"value": round(ride, 1), "unit": "s",
                              "unc": {"kind": "rel", "value": round(s_rel, 4)}},
    },
    "notes": "cover vs required floor: %.1fx (%.1f min against %.1f min)"
             % (ride / min_ride, ride / 60.0, min_ride / 60.0),
}, sys.stdout)
