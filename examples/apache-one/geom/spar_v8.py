"""Round tube spar — parametric geometry core.

Canonical definition of spar_v8's shape (spec §6.2). Outputs section properties
and mass; claims manufacturing features for the DFM ruleset; asserts its own
topology so a bad regeneration fails loudly instead of making a wrong part.
"""

import json
import math
import sys

p = json.load(sys.stdin)
P = {k: v["si"] for k, v in p["params"].items()}
od = P["outer_diameter"]      # m
wall = P["wall"]              # m
length = P["length"]          # m
rho = p["inputs"]["density"]["si"]  # kg/m^3

id_ = od - 2.0 * wall
area = math.pi / 4.0 * (od**2 - id_**2)          # m^2
Ixx = math.pi / 64.0 * (od**4 - id_**4)          # m^4
volume = area * length                            # m^3
mass = volume * rho                               # kg

json.dump({
    "outputs": {
        "mass": {"value": mass * 1e3, "unit": "g", "unc": {"kind": "rel", "value": 0.03}},
        "section_Ixx": {"value": Ixx * 1e12, "unit": "mm^4"},
        "section_area": {"value": area * 1e6, "unit": "mm^2"},
        "volume": {"value": volume * 1e9, "unit": "mm^3"},
        "outer_radius": {"value": od / 2.0 * 1e3, "unit": "mm"},
    },
    "features": {
        "min_wall_thickness": {"value": wall * 1e3, "unit": "mm"},
        "min_internal_radius": {"value": id_ / 2.0 * 1e3, "unit": "mm"},
        "sharp_internal_corner_count": {"value": 0},
    },
    "assertions": [
        {"name": "closed_tube_section", "passed": id_ > 0.0,
         "detail": f"inner diameter {id_*1e3:.2f} mm"},
        {"name": "thin_wall_regime", "passed": wall / od < 0.2,
         "detail": "section formulas assume a thin-walled tube"},
        {"name": "wall_positive", "passed": wall > 0.0},
    ],
}, sys.stdout)
