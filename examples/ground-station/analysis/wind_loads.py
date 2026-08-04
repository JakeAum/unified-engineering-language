"""Wind loads on the 5 m dish (req ENV-004).

Quasi-steady bluff-body drag: F = 1/2 rho v^2 Cd A, face-on worst case at the
operational wind; overturning moment through the aperture-centroid arm. The
survival case is zenith-stowed (Cd*A knocked down by the stow factor) at the
survival wind, with the 3 s gust pressure factor on top — the conservative
reading of an unqualified survival speed.
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


v_op = I["wind_op"]                # m/s
v_sv = I["wind_survival"]          # m/s
A = I["frontal_area"]              # m^2
rho = P["rho_air"]                 # kg/m^3
cd = P["cd_face_on"]
gust = P["gust_factor"]
stow = P["stow_drag_factor"]
arm = P["moment_arm"]              # m

q_op = 0.5 * rho * v_op**2                          # Pa
drag = q_op * cd * A                                # N, face-on, operational mean
moment = drag * arm                                 # N*m about the bearing plane
q_sv = 0.5 * rho * v_sv**2
survival = q_sv * cd * A * stow * gust * arm        # N*m, stowed, gust pressure

cd_rel = rel(p["params"], "cd_face_on", 0.10)
stow_rel = rel(p["params"], "stow_drag_factor", 0.30)
arm_rel = rel(p["params"], "moment_arm", 0.10)
drag_rel = round(math.sqrt(cd_rel**2 + 0.05**2), 2)          # +5% blockage/shape model
moment_rel = round(math.sqrt(drag_rel**2 + arm_rel**2), 2)
survival_rel = round(math.sqrt(cd_rel**2 + stow_rel**2 + arm_rel**2), 2)

json.dump({
    "outputs": {
        "drag_force": {"value": round(drag / 1e3, 4), "unit": "kN",
                       "unc": {"kind": "rel", "value": drag_rel}},
        "overturning_moment": {"value": round(moment / 1e3, 4), "unit": "kN*m",
                               "unc": {"kind": "rel", "value": moment_rel}},
        "survival_moment": {"value": round(survival / 1e3, 4), "unit": "kN*m",
                            "unc": {"kind": "rel", "value": survival_rel}},
    },
    "notes": f"q_op = {q_op:.1f} Pa face-on; survival case stowed at zenith with gust pressure factor {gust:g}",
}, sys.stdout)
