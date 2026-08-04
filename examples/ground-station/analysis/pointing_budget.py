"""RSS pointing budget and beam loss (req PNT-003).

Terms: servo residual, encoder/mount alignment, wind gust deflection (the full
operational overturning moment across the locked-rotor stiffness — conservative,
since the servo tracks out the mean), ephemeris/time-tag, thermal distortion.
Root-sum-squared as independent errors; beam loss = 12 (theta/HPBW)^2 dB.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

DEG = math.pi / 180.0

hpbw = I["hpbw"] / DEG             # deg (si carries angle as dimensionless rad)
M_gust = I["gust_moment"]          # N*m
k = I["stiffness"]                 # N*m/rad
max_err = I["max_err"] / DEG       # deg

servo = P["servo_error"] / DEG     # deg
encoder = P["encoder_error"] / DEG
ephem = P["ephemeris_error"] / DEG
thermal = P["thermal_error"] / DEG
wind = (M_gust / k) / DEG          # rad -> deg

terms = {"servo": servo, "encoder": encoder, "wind": wind,
         "ephemeris": ephem, "thermal": thermal}
total = math.sqrt(sum(t**2 for t in terms.values()))    # deg
loss_db = 12.0 * (total / hpbw) ** 2                    # dB

# sensitivity-weighted uncertainty: servo ±20% and thermal ±30% dominate the RSS
share = {n: t**2 / total**2 for n, t in terms.items()}
total_rel = round(math.sqrt((share["servo"] * 0.20) ** 2
                            + (share["thermal"] * 0.30) ** 2
                            + (share["wind"] * 0.15) ** 2), 2)
loss_rel = min(2.0 * total_rel, 0.5)                    # loss is quadratic in theta

json.dump({
    "outputs": {
        "total_pointing_error": {"value": round(total, 4), "unit": "deg",
                                 "unc": {"kind": "rel", "value": total_rel}},
        "pointing_loss_db": {"value": round(loss_db, 4), "unit": "dB",
                             "unc": {"kind": "rel", "value": loss_rel}},
    },
    "notes": (f"terms [deg]: " + ", ".join(f"{n} {t:.4f}" for n, t in terms.items())
              + f"; margin to req {max_err:.3f} deg: {max_err - total:.4f} deg"),
}, sys.stdout)
