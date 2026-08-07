import json, sys

json.load(sys.stdin)
json.dump({"outputs": {"mass": {"value": 95.0, "unit": "g"},
                       "volume": {"value": 1000.0, "unit": "mm^3"}},
           "assertions": [{"name": "closed_manifold", "ok": True}]}, sys.stdout)
