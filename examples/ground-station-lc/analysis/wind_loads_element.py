"""Wind moments on one 3.0 m element: full-track, operational-hold, survival."""
import json, math, sys
p = json.load(sys.stdin)
I = {k: v["si"] for k, v in p["inputs"].items()}
P = {k: v["si"] for k, v in p["params"].items()}

def moment(v, cda_factor=1.0, gust=1.0):
    q = 0.5 * P["rho_air"] * v * v
    return q * P["cd"] * P["frontal_area"] * cda_factor * gust * P["moment_arm"]

g = P["gust_factor"]
m_track = moment(I["wind_full_track"], gust=g)
m_op = moment(I["wind_operational"], gust=g)
m_surv = moment(I["wind_survival"], cda_factor=P["stow_drag_factor"], gust=g)
hold_margin = I["hold_torque"] / m_op

json.dump({"outputs": {
    "gust_moment_full_track": {"value": round(m_track / 1e3, 4), "unit": "kN*m",
                               "unc": {"kind": "rel", "value": 0.15}},
    "gust_moment_operational": {"value": round(m_op / 1e3, 4), "unit": "kN*m",
                                "unc": {"kind": "rel", "value": 0.15}},
    "survival_moment": {"value": round(m_surv / 1e3, 4), "unit": "kN*m",
                        "unc": {"kind": "rel", "value": 0.33}},
    "hold_margin": {"value": round(hold_margin, 3), "unit": "",
                    "unc": {"kind": "rel", "value": 0.15}},
}, "notes": "survival moment reacts through the earth anchors; ballast alone is not enough and the site kit says so"},
          sys.stdout)
