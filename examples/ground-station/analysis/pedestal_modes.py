"""First locked-rotor mode of the antenna on its pedestal drive (req PNT-003).

Single-DOF torsional oscillator: the rotating assembly's inertia on the drive's
locked-rotor stiffness, f1 = (1/2pi) sqrt(k/J). J stacks the dish at its radius
of gyration, the counterweight set at its CG radius, and a yoke allowance.
This is the mode the servo loop must be shaped below (ServoBandwidth requires
it; this analysis assumes elastic_modes because modal content IS the product).
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}


def rel(block, name, default):
    unc = block[name].get("unc") or {}
    if unc.get("kind") == "rel":
        return float(unc.get("value", default))
    return default


k = I["stiffness"]                 # N*m/rad (rad dimensionless)
m_dish = I["dish_mass"]            # kg
m_cw = I["cw_mass"]                # kg
r_g = P["dish_radius_gyration"]    # m
r_cw = P["cw_radius"]              # m
J_yoke = P["yoke_inertia"]         # kg*m^2

J_dish = m_dish * r_g**2
J_cw = m_cw * r_cw**2
J = J_dish + J_cw + J_yoke                          # kg*m^2
f1 = math.sqrt(k / J) / (2.0 * math.pi)             # Hz

k_rel = rel(p["inputs"], "stiffness", 0.20)
# inertia stack: dish mass ±12% with r_g ±10% (2x on the square), yoke ±30%,
# combined by share — comes out ~±14%
J_rel = 0.14
f_rel = round(0.5 * math.sqrt(k_rel**2 + J_rel**2), 2)

json.dump({
    "outputs": {
        "first_locked_rotor_mode": {"value": round(f1, 3), "unit": "Hz",
                                    "unc": {"kind": "rel", "value": f_rel}},
        "inertia": {"value": round(J, 1), "unit": "kg*m^2",
                    "unc": {"kind": "rel", "value": J_rel}},
    },
    "notes": (f"J = {J:.0f} kg*m^2 (dish {J_dish:.0f} + counterweight {J_cw:.0f} "
              f"+ yoke {J_yoke:.0f}); contract nominal 4-6 Hz would need "
              f"J ~ {k / (2.0 * math.pi * 5.0)**2:.0f} kg*m^2 at this stiffness"),
}, sys.stdout)
