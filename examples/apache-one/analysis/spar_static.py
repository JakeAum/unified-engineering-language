"""Spar static strength at the limit root bending moment (req STR-014).

Euler-Bernoulli, root treated rigid (declared in the framing with rationale).
Deflection uses the conservative tip-moment case.
"""

import json
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}

M = I["root_moment"]          # N*m
Ixx = I["section_Ixx"]        # m^4
c = I["outer_radius"]         # m
sigma_y = I["yield_strength"]  # Pa
E = I["E"]                    # Pa
L = I["length"]               # m

sigma = M * c / Ixx
FoS = sigma_y / sigma
deflection = M * L**2 / (2.0 * E * Ixx)

json.dump({
    "outputs": {
        "FoS": {"value": round(FoS, 4), "unit": "", "unc": {"kind": "rel", "value": 0.05}},
        "root_stress": {"value": round(sigma / 1e6, 2), "unit": "MPa", "unc": {"kind": "rel", "value": 0.04}},
        "max_deflection": {"value": round(deflection * 1e3, 2), "unit": "mm", "unc": {"kind": "rel", "value": 0.05}},
    },
}, sys.stdout)
