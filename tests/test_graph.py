"""Unit tests for the semantic graph model (may know internals; conformance may not)."""

import json
import unittest

from uel.canon import CanonError, canonical_bytes, canonical_str
from uel.graph import (
    Component,
    GraphDoc,
    Quantity,
    Uncertainty,
)


class TestCanon(unittest.TestCase):
    def test_sorted_compact(self):
        self.assertEqual(canonical_str({"b": 1, "a": [1.5, "x"]}), '{"a":[1.5,"x"],"b":1}')

    def test_rejects_nonfinite(self):
        with self.assertRaises(CanonError):
            canonical_bytes({"x": float("nan")})
        with self.assertRaises(CanonError):
            canonical_bytes({"x": float("inf")})

    def test_rejects_nonstring_keys_and_types(self):
        with self.assertRaises(CanonError):
            canonical_bytes({1: "x"})
        with self.assertRaises(CanonError):
            canonical_bytes({"x": {"y": object()}})

    def test_float_repr_shortest(self):
        self.assertEqual(canonical_str({"x": 0.1}), '{"x":0.1}')
        self.assertEqual(canonical_str({"x": 1e21}), '{"x":1e+21}')


class TestQuantity(unittest.TestCase):
    def test_omit_empty(self):
        q = Quantity(value=240.0, unit="g", unc=Uncertainty("abs", 10.0))
        self.assertEqual(q.to_obj(), {"value": 240.0, "unit": "g", "unc": {"kind": "abs", "value": 10.0}})
        self.assertEqual(Quantity().to_obj(), {})

    def test_interval_roundtrip(self):
        doc, errs = GraphDoc.from_obj(
            {
                "uel_schema": "0.2",
                "nodes": {
                    "c": {
                        "kind": "component",
                        "quantities": {"f": {"value": [0.0, 12.0], "unit": "kN"}},
                    }
                },
            }
        )
        self.assertEqual(errs, [])
        assert doc is not None
        c = doc.nodes["c"]
        assert isinstance(c, Component)
        self.assertEqual(c.quantities["f"].value, (0.0, 12.0))

    def test_bad_confidence_rejected(self):
        _, errs = GraphDoc.from_obj(
            {
                "uel_schema": "0.2",
                "nodes": {"c": {"kind": "component", "quantities": {"x": {"value": 1.0, "conf": 1.5}}}},
            }
        )
        self.assertTrue(any("confidence" in e.message for e in errs))


class TestGraphDoc(unittest.TestCase):
    def test_unknown_field_rejected(self):
        _, errs = GraphDoc.from_obj(
            {"uel_schema": "0.2", "nodes": {"c": {"kind": "component", "warp": 1}}}
        )
        self.assertTrue(any("unknown field" in e.message for e in errs))

    def test_schema_version_gate(self):
        _, errs = GraphDoc.from_obj({"uel_schema": "9.9", "nodes": {}})
        self.assertTrue(any("unsupported schema version" in e.message for e in errs))

    def test_connections_sorted_in_canonical(self):
        doc, errs = GraphDoc.from_obj(
            {
                "uel_schema": "0.2",
                "nodes": {},
                "connections": [
                    {"from": "b.p", "to": "c.q"},
                    {"from": "a.p", "to": "c.q"},
                ],
            }
        )
        self.assertEqual(errs, [])
        assert doc is not None
        obj = doc.to_obj()
        self.assertEqual([c["from"] for c in obj["connections"]], ["a.p", "b.p"])

    def test_fixpoint(self):
        raw = {
            "uel_schema": "0.2",
            "edition": "2026",
            "nodes": {
                "req.R1": {"kind": "requirement", "text": "hold", "quantities": {"limit": {"value": 5.0, "unit": "kN"}}},
                "A": {
                    "kind": "analysis",
                    "knowns": {"load": "req.R1.limit"},
                    "core": {"path": "a.py"},
                    "outputs": {"FoS": {"unc": True}},
                },
            },
        }
        doc, errs = GraphDoc.from_obj(raw)
        self.assertEqual(errs, [])
        assert doc is not None
        once = doc.to_canonical()
        doc2, errs2 = GraphDoc.from_obj(json.loads(once))
        self.assertEqual(errs2, [])
        assert doc2 is not None
        self.assertEqual(once, doc2.to_canonical())
        self.assertEqual(doc, doc2)


if __name__ == "__main__":
    unittest.main()
