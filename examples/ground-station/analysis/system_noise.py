"""Receive system noise temperature at the LNA input (req LNK-002).

Lumped Friis-style stack, worst case at minimum elevation and enclosure hot
case:

  T_sys = T_ant + T_feedloss + T_lna(+drift) + T_downstream

with T_ant = zenith sky brightness x flat-atmosphere airmass + CMB + prime-
focus spillover; T_feedloss = T_phys (L - 1) for the feed ohmic loss L; a
small LNA noise-temperature drift above its 25 degC rating point; and the
post-LNA chain already referred through the 40 dB LNA gain (params). The
plain sum takes every term at its input-referred worst — conservative by a
few kelvin against strict single-plane bookkeeping.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}


def unc_abs(d: dict, default: float = 0.0) -> float:
    """Absolute 1-sigma uncertainty in SI terms. Every abs-unc quantity this
    core touches is in K, degC steps, or dB — all scale 1 in SI — and rel
    unc scales the SI value directly."""
    u = d.get("unc") or {}
    v = u.get("value")
    if not isinstance(v, (int, float)):
        return default
    if u.get("kind") == "rel":
        return abs(d["si"]) * v
    if u.get("kind") == "abs":
        return abs(v)
    return default


el = I["min_elevation"]          # rad (deg is dimensionless, pi/180)
airmass = 1.0 / math.sin(el)     # flat-atmosphere secant, valid above ~5 deg

t_sky = P["zenith_atm_temp"] * airmass + P["cmb_temp"]
t_ant = t_sky + P["spillover_temp"]

L = 10.0 ** (I["feed_loss_db"] / 10.0)
t_feed = P["feed_physical_temp"] * (L - 1.0)

dT = max(0.0, I["lna_physical_temp"] - P["lna_ref_temp"])  # no cold credit
drift = P["lna_drift_coeff"] * dT
t_lna = I["lna_noise_temp"] + drift

t_down = P["downstream_temp"]

t_sys = t_ant + t_feed + t_lna + t_down

# RSS of the declared term uncertainties, all in kelvin.
u_terms = [
    unc_abs(p["inputs"]["lna_noise_temp"]),                      # vendor Te
    unc_abs(p["params"]["zenith_atm_temp"]) * airmass,           # sky
    unc_abs(p["params"]["spillover_temp"]),                      # ground pickup
    P["feed_physical_temp"] * L * math.log(10.0) / 10.0
    * unc_abs(p["inputs"]["feed_loss_db"]),                      # loss in dB
    (L - 1.0) * unc_abs(p["params"]["feed_physical_temp"]),      # feed temp
    unc_abs(p["params"]["lna_drift_coeff"]) * dT,                # drift coeff
    P["lna_drift_coeff"] * unc_abs(p["inputs"]["lna_physical_temp"]),
    unc_abs(p["params"]["downstream_temp"]),                     # post-LNA
]
u_tsys = math.sqrt(sum(u * u for u in u_terms))

json.dump({
    "outputs": {
        "t_sys": {"value": round(t_sys, 2), "unit": "K",
                  "unc": {"kind": "abs", "value": round(u_tsys, 2)}},
    },
    "notes": (
        f"airmass {airmass:.2f} at min elevation; stack: T_ant {t_ant:.1f} K "
        f"(sky {t_sky:.1f} + spillover {P['spillover_temp']:.1f}), feed loss "
        f"{t_feed:.1f} K, LNA {t_lna:.1f} K (drift {drift:.1f}), downstream "
        f"{t_down:.2f} K; LNA hot-case flange {I['lna_physical_temp']:.1f} K."
    ),
}, sys.stdout)
