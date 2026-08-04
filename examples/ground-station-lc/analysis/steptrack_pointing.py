"""Steptrack pointing on consumer rotators: RSS of deadband, dither residual,
wind jitter, ephemeris bias; loss = 12*(theta/HPBW)^2 dB."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}
rad2deg = 180.0 / math.pi

hpbw = I["hpbw"] * rad2deg          # deg arrives as dimensionless rad in SI
backlash = I["backlash"] * rad2deg
frac = P["steptrack_residual_frac"]
wind = P["wind_jitter"] * rad2deg
ephem = P["ephemeris_bias"] * rad2deg

terms = [backlash / 2.0, frac * hpbw, wind, ephem]
theta = math.sqrt(sum(t * t for t in terms))
loss = 12.0 * (theta / hpbw) ** 2

json.dump({"outputs": {
    "total_pointing_error": {"value": round(theta, 4), "unit": "deg",
                             "unc": {"kind": "rel", "value": 0.25}},
    "pointing_loss_db": {"value": round(loss, 4), "unit": "dB",
                         "unc": {"kind": "rel", "value": 0.5}},
}, "notes": f"terms deg: deadband {terms[0]:.3f}, steptrack {terms[1]:.3f}, wind {terms[2]:.3f}, ephem {terms[3]:.3f}; HPBW {hpbw:.3f}"},
          sys.stdout)
