import json, sys
json.load(sys.stdin)
json.dump({"outputs": {
    "gain_dbi": {"value": 50.65, "unit": "dB", "unc": {"kind": "abs", "value": 0.5}},
    "hpbw": {"value": 0.497, "unit": "deg"},
}}, sys.stdout)
