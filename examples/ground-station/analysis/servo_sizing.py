"""Azimuth drive sizing in operational wind (req ENV-004).

Quasi-static: peak torque is the wind overturning moment held at the output,
plus the small inertial torque to accelerate the mount to slew rate. Peak
drive power is that torque delivered at slew rate through the drivetrain
efficiency. Tracking at 0.004 deg/s costs about a watt — the drive is sized
by wind and slew, not by the L1 track.
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


M_wind = I["overturning_moment"]   # N*m
track = I["track_rate"]            # rad/s (deg is dimensionless pi/180)
w_slew = P["slew_rate"]            # rad/s
a_slew = P["slew_accel"]           # rad/s^2
J = P["rotating_inertia"]          # kg*m^2
eta = P["drive_efficiency"]

T_accel = J * a_slew                                # N*m
T_peak = M_wind + T_accel                           # N*m at the output
P_peak = T_peak * w_slew / eta                      # W at the drive input
P_track = M_wind * track / eta                      # W, for the note

M_rel = rel(p["inputs"], "overturning_moment", 0.15)
eta_rel = rel(p["params"], "drive_efficiency", 0.05)
T_rel = round(M_rel, 2)                             # accel term is ~1% of the total
P_rel = round(math.sqrt(M_rel**2 + eta_rel**2), 2)

json.dump({
    "outputs": {
        "peak_torque": {"value": round(T_peak / 1e3, 4), "unit": "kN*m",
                        "unc": {"kind": "rel", "value": T_rel}},
        "peak_drive_power": {"value": round(P_peak, 1), "unit": "W",
                             "unc": {"kind": "rel", "value": P_rel}},
    },
    "notes": (f"accel torque {T_accel:.0f} N*m is {100.0 * T_accel / T_peak:.1f}% of peak; "
              f"tracking power {P_track:.1f} W; azimuth worst case, elevation similar and "
              f"non-simultaneous at full rate"),
}, sys.stdout)
