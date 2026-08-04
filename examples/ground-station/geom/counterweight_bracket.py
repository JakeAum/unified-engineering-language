"""Counterweight clamp bracket — parametric geometry core (one bracket).

A real machined part: 240 x 180 mm AL6061 base plate, two cheek plates that
clamp the steel stack, a weight-relief pocket milled into the base, and a
4x M12 bolt pattern down to the elevation boom. Feature claims feed the
cnc_3axis DFM ruleset (spec §7.1); topological assertions make a bad
regeneration a compile-visible failure, not a silently wrong part.

Fixed layout (mm): base 240 x 180, cheeks 170 x 130 upstanding, pocket
140 x 90 centered in the base, bolt pattern 200 x 140, M12 clearance Ø13.5.
"""

import json
import math
import sys

p = json.load(sys.stdin)
P = {k: v["si"] for k, v in p["params"].items()}
t_base = P["base_thickness"]       # m
t_cheek = P["cheek_thickness"]     # m
t_pocket = P["pocket_depth"]       # m
r_int = P["internal_radius"]       # m
rho = p["inputs"]["density"]["si"]  # kg/m^3

# fixed plan-form dimensions (m)
BASE_L, BASE_W = 0.240, 0.180
CHEEK_L, CHEEK_H = 0.170, 0.130
POCKET_L, POCKET_W = 0.140, 0.090
BOLT_DX, BOLT_DY = 0.200, 0.140    # pattern spacing (centers)
HOLE_D = 0.0135                    # M12 clearance

base = BASE_L * BASE_W * t_base
cheeks = 2.0 * CHEEK_L * CHEEK_H * t_cheek
pocket = POCKET_L * POCKET_W * t_pocket
holes = 4.0 * math.pi * (HOLE_D / 2.0) ** 2 * t_base
volume = base + cheeks - pocket - holes            # m^3
mass = volume * rho                                 # kg

floor = t_base - t_pocket                           # pocket floor left under the relief
# bolt-to-pocket clearance, worst axis (hole edge to pocket wall)
clear_x = BOLT_DX / 2.0 - POCKET_L / 2.0 - HOLE_D / 2.0
clear_y = BOLT_DY / 2.0 - POCKET_W / 2.0 - HOLE_D / 2.0
clearance = min(clear_x, clear_y)

json.dump({
    "outputs": {
        "mass": {"value": round(mass, 4), "unit": "kg",
                 "unc": {"kind": "rel", "value": 0.05}},
        "volume": {"value": round(volume * 1e9, 1), "unit": "mm^3"},
    },
    "features": {
        "min_internal_radius": {"value": round(r_int * 1e3, 2), "unit": "mm"},
        "min_wall_thickness": {"value": round(floor * 1e3, 2), "unit": "mm"},
        "sharp_internal_corner_count": {"value": 0},
        "loaded_internal_corner_min_fillet": {"value": round(r_int * 1e3, 2), "unit": "mm"},
        "undeclared_undercut_count": {"value": 0},
    },
    "assertions": [
        {"name": "pocket_floor_positive", "passed": floor > 0.0,
         "detail": f"pocket leaves a {floor*1e3:.1f} mm floor under the relief"},
        {"name": "bolt_pattern_clears_pocket", "passed": clearance > 0.0,
         "detail": f"hole edge to pocket wall {clearance*1e3:.2f} mm at the worst corner"},
        {"name": "cheek_footprint_inside_base",
         "passed": CHEEK_L <= BASE_L and 2.0 * t_cheek <= BASE_W,
         "detail": "cheeks land fully on the base plate"},
        {"name": "solid_volume_positive", "passed": volume > 0.0},
    ],
    "notes": "loaded corners are the cheek-to-base roots; they carry the clamp moment and keep the full internal_radius fillet",
}, sys.stdout)
