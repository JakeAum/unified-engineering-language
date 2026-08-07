import json, sys

json.load(sys.stdin)
json.dump({"outputs": {"y": {"value": 1.0, "unit": "m"}}}, sys.stdout)
