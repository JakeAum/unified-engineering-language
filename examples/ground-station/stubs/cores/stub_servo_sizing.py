import json, sys
json.load(sys.stdin)
json.dump({"outputs": {
    "peak_torque": {"value": 19.0, "unit": "kN*m", "unc": {"kind": "rel", "value": 0.2}},
    "peak_drive_power": {"value": 2200.0, "unit": "W", "unc": {"kind": "rel", "value": 0.2}},
}}, sys.stdout)
