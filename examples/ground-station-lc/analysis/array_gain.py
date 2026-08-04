"""Effective gain of N coherently combined identical apertures with Ruze loss."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

c = 299792458.0
lam = c / I["freq"]
D = I["diameter"]
eta = I["efficiency"]
eps = I["surface_rms"]
n = P["n_elements"]
comb = P["combining_loss_db"]

g_ideal = 10.0 * math.log10(eta * (math.pi * D / lam) ** 2)
ruze = 4.343 * (4.0 * math.pi * eps / lam) ** 2
g_elem = g_ideal - ruze
g_array = g_elem + 10.0 * math.log10(n) - comb
hpbw = 70.0 * lam / D                                  # degrees

json.dump({"outputs": {
    "g_array_dbi": {"value": round(g_array, 3), "unit": "dB",
                    "unc": {"kind": "abs", "value": 0.4}},
    "element_gain_dbi": {"value": round(g_elem, 3), "unit": "dB",
                         "unc": {"kind": "abs", "value": 0.3}},
    "hpbw": {"value": round(hpbw, 4), "unit": "deg"},
}, "notes": f"element ideal {g_ideal:.2f} dBi, Ruze {ruze:.3f} dB, array factor {10.0*math.log10(n):.2f} dB, combining loss {comb:g} dB"},
          sys.stdout)
