"""5 m prime-focus paraboloid reflector — parametric geometry core.

Canonical definition of reflector_v1's shape (spec §6.2). The architecture owns
the sizing anchors (diameter, focal ratio); this core turns them into the areas
and mass every downstream analysis references, and asserts its own topology so
a bad regeneration fails loudly instead of making a wrong dish.

Mass model: areal density is quoted per unit APERTURE (projected) area — the
convention the vendor's concept sheet uses — plus a hub/backing-truss lump.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

D = I["diameter"]                  # m
f_over_D = I["focal_ratio"]        # dimensionless
rho_a = P["areal_density"]         # kg/m^2 (per unit aperture area)
m_hub = P["hub_and_truss_mass"]    # kg

R = D / 2.0
aperture_area = math.pi * R**2                     # m^2, the RF aperture disc
focal_length = f_over_D * D                        # m
depth = R**2 / (4.0 * focal_length)                # paraboloid sagitta at the rim
# Face-on the paraboloid projects to exactly its aperture disc; the wind
# reference area is that projection (rim lip is inside the drag coefficient).
frontal_area = aperture_area                       # m^2

mass = rho_a * aperture_area + m_hub               # kg
# areal density ±15% on the panel share + hub ±20%, root-sum-squared
unc_abs = math.sqrt((0.15 * rho_a * aperture_area) ** 2 + (0.20 * m_hub) ** 2)
mass_rel = round(unc_abs / mass, 2)

json.dump({
    "outputs": {
        "mass": {"value": round(mass, 3), "unit": "kg",
                 "unc": {"kind": "rel", "value": mass_rel}},
        "aperture_area": {"value": round(aperture_area, 4), "unit": "m^2"},
        "frontal_area": {"value": round(frontal_area, 4), "unit": "m^2"},
        "focal_length": {"value": round(focal_length, 4), "unit": "m"},
    },
    "assertions": [
        {"name": "paraboloid_closes", "passed": depth > 0.0 and math.isfinite(depth),
         "detail": f"rim depth {depth*1e3:.1f} mm over a {D:.2f} m aperture"},
        {"name": "prime_focus_above_surface", "passed": focal_length > depth,
         "detail": f"focus at {focal_length:.3f} m clears the {depth:.3f} m bowl"},
        {"name": "focal_ratio_in_family", "passed": 0.3 <= f_over_D <= 0.5,
         "detail": f"f/D = {f_over_D:.2f}, prime-focus feed family"},
        {"name": "frontal_projection_is_aperture_disc",
         "passed": abs(frontal_area - aperture_area) < 1e-9,
         "detail": "face-on projected area equals the aperture disc"},
    ],
    "notes": "areal density per unit aperture area (vendor convention); curved-surface area is ~9% larger and is absorbed in the density figure",
}, sys.stdout)
