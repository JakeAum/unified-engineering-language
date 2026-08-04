"""Reduced-order flutter clearance (req AER-009).

Mass-ratio scaling estimate: V_f ≈ ω₁ · b · √μ with μ = m̄/(πρb²).
A correlation-grade model, declared as such; its envelope is fenced to
incompressible Mach and its margin is judged, not trusted.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

f1 = I["f1"]                # Hz (1/s)
m_bar = I["m_bar"]          # kg/m
V_NE = I["V_NE"]            # m/s
b = P["semichord"]          # m
rho = P["rho_air"]          # kg/m^3

mu = m_bar / (math.pi * rho * b**2)
omega1 = 2.0 * math.pi * f1
V_f = omega1 * b * math.sqrt(mu)
margin = V_f / V_NE

json.dump({
    "outputs": {
        "flutter_speed": {"value": round(V_f, 3), "unit": "m/s",
                          "unc": {"kind": "rel", "value": 0.12}},
        "flutter_margin": {"value": round(margin, 4), "unit": "",
                           "unc": {"kind": "rel", "value": 0.12}},
    },
}, sys.stdout)
