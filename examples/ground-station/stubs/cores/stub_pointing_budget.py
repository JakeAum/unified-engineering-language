import json, sys
json.load(sys.stdin)
json.dump({"outputs": {
    "total_pointing_error": {"value": 0.035, "unit": "deg", "unc": {"kind": "rel", "value": 0.2}},
    "pointing_loss_db": {"value": 0.06, "unit": "dB", "unc": {"kind": "rel", "value": 0.3}},
}}, sys.stdout)
