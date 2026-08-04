"""Station figure of merit G/T referenced at the LNA input (req LNK-002).

G/T = gain_dbi - feed_loss_db - 10 log10(T_sys): the aperture gain carried
through the feed ohmic loss to the LNA flange, over the system noise
temperature standing at that same plane.
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}


def unc_abs(d: dict, default: float = 0.0) -> float:
    """Absolute 1-sigma in SI terms; dB and K inputs here are all scale 1."""
    u = d.get("unc") or {}
    v = u.get("value")
    if not isinstance(v, (int, float)):
        return default
    if u.get("kind") == "rel":
        return abs(d["si"]) * v
    if u.get("kind") == "abs":
        return abs(v)
    return default


gain = I["gain_dbi"]          # dBi at the aperture
feed_loss = I["feed_loss_db"]  # dB, aperture to LNA flange
t_sys = I["t_sys"]            # K, at the LNA input

g_over_t = gain - feed_loss - 10.0 * math.log10(t_sys)

# RSS in dB: gain and loss enter directly; T_sys through 10/ln10 * dT/T.
u_t_db = (10.0 / math.log(10.0)) * unc_abs(p["inputs"]["t_sys"]) / t_sys
u = math.sqrt(
    unc_abs(p["inputs"]["gain_dbi"]) ** 2
    + unc_abs(p["inputs"]["feed_loss_db"]) ** 2
    + u_t_db ** 2
)

json.dump({
    "outputs": {
        "g_over_t_dbk": {"value": round(g_over_t, 3), "unit": "dB",
                         "unc": {"kind": "abs", "value": round(u, 3)}},
    },
    "notes": (
        f"net gain at LNA input {gain - feed_loss:.3f} dBi over "
        f"10log10({t_sys:.2f} K) = {10.0 * math.log10(t_sys):.3f}; "
        "T_sys term dominates the uncertainty."
    ),
}, sys.stdout)
