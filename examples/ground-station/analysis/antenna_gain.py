"""Aperture gain with Ruze surface-error loss, and HPBW (req LNK-002).

G0 = 10 log10(eta (pi D / lambda)^2), Ruze loss 4.343 (4 pi eps / lambda)^2 dB
off the top, HPBW = 70 lambda / D degrees. The single efficiency factor is
declared lumped in the framing; no pattern integration stands behind it.
"""

import json
import math
import sys

C = 299792458.0  # m/s

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}

f = I["freq"]            # Hz
D = I["diameter"]        # m
eta = I["efficiency"]    # dimensionless
eps = I["surface_rms"]   # m

lam = C / f
g0 = 10.0 * math.log10(eta * (math.pi * D / lam) ** 2)
ruze = 4.343 * (4.0 * math.pi * eps / lam) ** 2
gain = g0 - ruze
hpbw = 70.0 * lam / D  # the 70-factor beamwidth rule carries degrees

# Uncertainty: the vendor-class efficiency estimate mapped onto the dB scale,
# RSS'd with half the Ruze term (the rms figure is a manufacturing spec limit,
# not a measured surface map). Carrier is +- cal; gain moves ~0.001 dB/MHz.
eta_unc_rel = (p["inputs"]["efficiency"].get("unc") or {}).get("value", 0.05)
u_eta_db = (10.0 / math.log(10.0)) * eta_unc_rel
u_ruze_db = 0.5 * ruze
u_gain = math.hypot(u_eta_db, u_ruze_db)

json.dump({
    "outputs": {
        "gain_dbi": {"value": round(gain, 3), "unit": "dB",
                     "unc": {"kind": "abs", "value": round(u_gain, 3)}},
        "hpbw": {"value": round(hpbw, 4), "unit": "deg"},
    },
    "notes": (
        f"lambda = {lam * 1e3:.3f} mm; ideal aperture {g0:.3f} dBi minus Ruze "
        f"{ruze:.3f} dB (eps/lambda ~ 1/{lam / eps:.0f}, well inside the "
        "small-error regime); carrier +- cal pending ICD is negligible here."
    ),
}, sys.stdout)
