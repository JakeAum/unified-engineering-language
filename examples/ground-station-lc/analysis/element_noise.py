"""One array element's system noise at the LNA input, single-plane additive
convention (matches the baseline station's bookkeeping)."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

airmass = 1.0 / math.sin(I["min_elevation"])          # flat atmosphere, rad in
t_sky = P["zenith_atm_temp"] * airmass + P["cmb_temp"]
L_feed = 10.0 ** (I["feed_loss_db"] / 10.0)
t_feed = (L_feed - 1.0) * P["feed_physical_temp"]
t_sys = t_sky + P["spillover_temp"] + t_feed + I["lna_noise_temp"] + P["downstream_temp"]

rel = math.sqrt((0.3 * (P["zenith_atm_temp"] * airmass) / t_sys) ** 2
                + (0.3 * P["spillover_temp"] / t_sys) ** 2
                + (0.2 * I["lna_noise_temp"] / t_sys) ** 2)
json.dump({"outputs": {"t_sys": {"value": round(t_sys, 2), "unit": "K",
                                  "unc": {"kind": "rel", "value": round(rel, 3)}}},
           "notes": f"sky {t_sky:.1f} K at airmass {airmass:.2f}; feed {t_feed:.1f} K; single-plane additive"},
          sys.stdout)
