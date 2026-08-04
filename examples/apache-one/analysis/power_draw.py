"""Cruise power chain (req PWR-021): shaft power → bus current and ESC heat.

Worst-case bus current at the low end of the battery voltage window (the
interval input arrives as [lo, hi] in SI).
"""

import json
import sys

p = json.load(sys.stdin)

shaft = p["inputs"]["shaft_power"]["si"]          # W
v_lo, v_hi = p["inputs"]["v_bus"]["si"]           # V window
eta_m = p["params"]["eta_motor"]["si"]
eta_e = p["params"]["eta_esc"]["si"]

p_motor_in = shaft / eta_m          # electrical into motor
p_esc_in = p_motor_in / eta_e       # electrical into ESC
esc_loss = p_esc_in - p_motor_in    # heat in the ESC
i_max = p_esc_in / v_lo             # worst case at sag

json.dump({
    "outputs": {
        "bus_current_max": {"value": round(i_max, 2), "unit": "A",
                            "unc": {"kind": "rel", "value": 0.05}},
        "esc_loss": {"value": round(esc_loss, 2), "unit": "W",
                     "unc": {"kind": "rel", "value": 0.15}},
        "esc_input_power": {"value": round(p_esc_in, 1), "unit": "W",
                            "unc": {"kind": "rel", "value": 0.04}},
    },
}, sys.stdout)
