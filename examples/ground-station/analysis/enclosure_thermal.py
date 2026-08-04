"""LNA enclosure temperatures at the site extremes (req ENV-004), lumped node.

Hot case (45 degC ambient, heater off, TEC and solar shield engaged):
    T_box = T_amb_max + (q_internal + q_solar_residual - q_cool) / UA
Cold case (-30 degC ambient, TEC off, thermostat holds the setpoint):
    heater_duty = UA * (heater_setpoint - T_amb_min) / heater_power
(the internal-dissipation credit is deliberately not taken in the cold case —
conservative on duty).

Affine temperatures arrive in kelvin via `si`; outputs are returned in kelvin
and the shell converts the declared degC output back. Uncertainties propagate
as RSS over the declared relative bands (first-order sensitivities).
"""

import json
import math
import sys

p = json.load(sys.stdin)
I = p["inputs"]
P = p["params"]


def si(e):
    return e["si"]


def sigma(e):
    u = e.get("unc")
    if not u or u.get("kind") != "rel":
        return 0.0
    return abs(si(e)) * float(u.get("value", 0.0))


t_amb_min = si(I["t_amb_min"])        # K
t_amb_max = si(I["t_amb_max"])        # K
heater = si(I["heater_power"])        # W
ua = si(P["ua"])                      # W/K
q_int = si(P["q_internal"])           # W
q_solar = si(P["q_solar_residual"])   # W
q_cool = si(P["q_cool"])              # W
setpoint = si(P["heater_setpoint"])   # K

# -- hot case: net load into the box is negative with the TEC on -------------
q_net = q_int + q_solar - q_cool                  # W (negative: TEC wins)
t_hot = t_amb_max + q_net / ua                    # K

s_qnet = math.sqrt(sigma(P["q_internal"]) ** 2
                   + sigma(P["q_solar_residual"]) ** 2
                   + sigma(P["q_cool"]) ** 2)
# dT/d(ua) = -q_net/ua^2 ; dT/d(q) = 1/ua
s_thot = math.sqrt((s_qnet / ua) ** 2 + (abs(q_net) / ua * (sigma(P["ua"]) / ua)) ** 2)

# -- cold case: thermostat duty to hold the setpoint against -30 degC --------
duty = ua * (setpoint - t_amb_min) / heater       # dimensionless, must be < 1
s_duty = duty * (sigma(P["ua"]) / ua)             # setpoint and heater are exact

json.dump({
    "outputs": {
        "lna_physical_temp": {"value": round(t_hot, 2), "unit": "K",
                              "unc": {"kind": "abs", "value": round(s_thot, 2)}},
        "heater_duty": {"value": round(duty, 4), "unit": "",
                        "unc": {"kind": "abs", "value": round(s_duty, 4)}},
    },
    "notes": "hot case reported (envelope guarantee is checked at the seam); "
             "cold-case interior rides the 10 degC setpoint, duty %.2f leaves "
             "heater authority in reserve" % duty,
}, sys.stdout)
