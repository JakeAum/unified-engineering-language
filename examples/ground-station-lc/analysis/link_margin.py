"""I-ALiRT downlink budget at maximum L1 range (req LNK-002).

C/N0 = EIRP - FSPL - atm - rain - pol - pointing + G/T + 228.6
Eb/N0 = C/N0 - 10 log10(rate)
margin = Eb/N0 - (required Eb/N0 + implementation loss)

FSPL = 20 log10(4 pi R / lambda). Every declared loss is taken simultaneously
(worst-case snapshot, per the framing); 228.6 is the -10log10(k) Boltzmann
term of the contract.
"""

import json
import math
import sys

C = 299792458.0  # m/s
K_TERM_DB = 228.6  # -10log10(k), contract value

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}


def unc_abs(d: dict, default: float = 0.0) -> float:
    """Absolute 1-sigma in SI terms; dB inputs here are all scale 1.
    Calibration-pending ('cal') uncertainty carries no number — noted, not
    summed."""
    u = d.get("unc") or {}
    v = u.get("value")
    if not isinstance(v, (int, float)):
        return default
    if u.get("kind") == "rel":
        return abs(d["si"]) * v
    if u.get("kind") == "abs":
        return abs(v)
    return default


eirp = I["eirp_dbw"]        # dBW carried as dB ratio, reference in the name
R = I["max_range"]          # m
f = I["freq"]               # Hz
rate = I["data_rate"]       # 1/s information bit rate

lam = C / f
fspl = 20.0 * math.log10(4.0 * math.pi * R / lam)

losses = (I["atm_loss_db"] + I["rain_alloc_db"] + I["pol_loss_db"]
          + I["pointing_loss_db"])

cn0 = eirp - fspl - losses + I["g_over_t_dbk"] + K_TERM_DB
ebn0 = cn0 - 10.0 * math.log10(rate)
margin = ebn0 - (I["required_ebn0_db"] + I["impl_loss_db"])

# RSS of the numerically declared uncertainties (G/T and pointing loss carry
# them; EIRP is +- cal — the doubt of record, excluded from the number).
u = math.hypot(
    unc_abs(p["inputs"]["g_over_t_dbk"]),
    unc_abs(p["inputs"]["pointing_loss_db"]),
)

meets = margin >= I["min_margin_db"]

json.dump({
    "outputs": {
        "cn0_dbhz": {"value": round(cn0, 3), "unit": "dB",
                     "unc": {"kind": "abs", "value": round(u, 3)}},
        "ebn0_db": {"value": round(ebn0, 3), "unit": "dB",
                    "unc": {"kind": "abs", "value": round(u, 3)}},
        "margin_db": {"value": round(margin, 3), "unit": "dB",
                      "unc": {"kind": "abs", "value": round(u, 3)}},
    },
    "notes": (
        f"FSPL {fspl:.3f} dB at {R / 1e3:.0f} km, lambda {lam * 1e3:.3f} mm; "
        f"declared losses {losses:.2f} dB; margin {margin:.3f} dB "
        f"{'meets' if meets else 'MISSES'} the {I['min_margin_db']:.1f} dB "
        "floor; EIRP is +- cal from the ICD draft and moves margin 1:1."
    ),
}, sys.stdout)
