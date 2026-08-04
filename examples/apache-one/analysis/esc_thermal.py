"""ESC case temperature on a hot day (req THM-007), lumped R-chain.

T_case = T_amb + loss · (R_jc + R_sa). Affine temperatures arrive in kelvin
via `si`; the shell converts the declared degC output back.
"""

import json
import sys

p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

loss = I["esc_loss"]        # W
r_jc = I["R_jc"]            # K/W
t_amb = I["T_amb"]          # K
t_limit = I["T_limit"]      # K
r_sa = P["R_sa"]            # K/W

t_case = t_amb + loss * (r_jc + r_sa)
margin = t_limit - t_case

json.dump({
    "outputs": {
        "T_case": {"value": round(t_case, 2), "unit": "K",
                   "unc": {"kind": "abs", "value": 4.0}},
        "margin": {"value": round(margin, 2), "unit": "K",
                   "unc": {"kind": "abs", "value": 4.0}},
    },
}, sys.stdout)
