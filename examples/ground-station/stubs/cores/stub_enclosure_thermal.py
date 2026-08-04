import json, sys
json.load(sys.stdin)
json.dump({"outputs": {
    "lna_physical_temp": {"value": 28.0, "unit": "degC", "unc": {"kind": "abs", "value": 5.0}},
    "heater_duty": {"value": 0.3, "unit": "", "unc": {"kind": "rel", "value": 0.3}},
}}, sys.stdout)
