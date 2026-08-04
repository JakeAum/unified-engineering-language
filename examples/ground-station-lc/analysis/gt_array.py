"""Array G/T at the LNA input: array gain minus feed loss minus 10log10(T_sys)."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
gt = I["g_array_dbi"] - I["feed_loss_db"] - 10.0 * math.log10(I["t_sys"])
u_t = (p["inputs"]["t_sys"].get("unc") or {}).get("value", 0.08)
u = math.sqrt(0.4 ** 2 + (4.343 * u_t) ** 2)
json.dump({"outputs": {"g_over_t_dbk": {"value": round(gt, 3), "unit": "dB",
                                         "unc": {"kind": "abs", "value": round(u, 3)}}}},
          sys.stdout)
