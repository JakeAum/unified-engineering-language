"""First cantilever bending mode of the built-up wing panel (spar EI, panel mass).

f1 = (β₁²/2π)·√(EI / m̄L⁴), β₁ = 1.8751 for the first cantilever mode.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}

EI = I["E"] * I["section_Ixx"]   # N*m^2
L = I["length"]                  # m
m_bar = I["m_bar"]               # kg/m

beta1 = 1.8751
f1 = (beta1**2 / (2.0 * math.pi)) * math.sqrt(EI / (m_bar * L**4))

json.dump({
    "outputs": {
        "first_bending_mode": {"value": round(f1, 3), "unit": "Hz",
                               "unc": {"kind": "rel", "value": 0.08}},
    },
}, sys.stdout)
