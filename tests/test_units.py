import unittest

from uel.units import (
    D_ENERGY,
    D_FORCE,
    D_POWER,
    D_PRESSURE,
    DIMENSIONLESS,
    UnitError,
    check_effort_flow_power,
    dim_div,
    dim_mul,
    parse_unit,
)


class TestDimensionAlgebra(unittest.TestCase):
    def test_group_laws(self):
        n = parse_unit("N").dim
        m = parse_unit("m").dim
        self.assertEqual(dim_mul(n, m), D_ENERGY)
        self.assertEqual(dim_div(D_ENERGY, m), D_FORCE)
        self.assertEqual(dim_div(n, n), DIMENSIONLESS)

    def test_prefixes(self):
        self.assertAlmostEqual(parse_unit("kN").factor, 1e3)
        self.assertAlmostEqual(parse_unit("GPa").factor, 1e9)
        self.assertAlmostEqual(parse_unit("mm").factor, 1e-3)
        self.assertAlmostEqual(parse_unit("µm").factor, 1e-6)
        self.assertAlmostEqual(parse_unit("um").factor, 1e-6)
        # kg is prefix k on prefixable symbol g
        self.assertEqual(parse_unit("kg").dim, parse_unit("g").dim)
        self.assertAlmostEqual(parse_unit("kg").factor, 1.0)
        # exact symbol beats prefix decomposition: min is minutes, not milli-inch
        self.assertAlmostEqual(parse_unit("min").factor, 60.0)
        # T is tesla (exact), not tera-anything
        self.assertNotEqual(parse_unit("T").dim, DIMENSIONLESS)

    def test_composition(self):
        self.assertEqual(parse_unit("kg*m/s^2").dim, D_FORCE)
        self.assertEqual(parse_unit("kg/(m*s^2)").dim, D_PRESSURE)
        self.assertEqual(parse_unit("mm^4").dim, (0, 4, 0, 0, 0, 0, 0, 0))
        self.assertAlmostEqual(parse_unit("mm^4").factor, 1e-12)
        self.assertEqual(parse_unit("W/K").dim, dim_div(D_POWER, parse_unit("K").dim))

    def test_affine(self):
        c = parse_unit("degC")
        self.assertAlmostEqual(c.to_si(0.0), 273.15)
        self.assertAlmostEqual(c.to_si(100.0), 373.15)
        f = parse_unit("degF")
        self.assertAlmostEqual(f.to_si(32.0), 273.15, places=6)
        with self.assertRaises(UnitError):
            parse_unit("degC/W")
        with self.assertRaises(UnitError):
            parse_unit("mdegC")

    def test_angle_dimensionless_convention(self):
        self.assertEqual(parse_unit("rad").dim, DIMENSIONLESS)
        self.assertAlmostEqual(parse_unit("deg").factor, 3.141592653589793 / 180.0)
        # torque × angular velocity = power under the convention
        self.assertEqual(dim_mul(parse_unit("N*m").dim, parse_unit("rad/s").dim), D_POWER)
        self.assertAlmostEqual(parse_unit("rpm").factor, 2 * 3.141592653589793 / 60.0)

    def test_effort_flow_table(self):
        # every spec §2.2 row satisfies the kernel invariant
        for eff, flo in [("V", "A"), ("N", "m/s"), ("N*m", "rad/s"), ("Pa", "m^3/s"), ("K", "W/K")]:
            self.assertTrue(check_effort_flow_power(eff, flo), f"{eff} × {flo}")
        self.assertFalse(check_effort_flow_power("Pa", "m/s"))

    def test_suggestions(self):
        for bad, want in [("Watt", "W"), ("gramms", "g"), ("barr", "bar"), ("killograms", "kg")]:
            with self.assertRaises(UnitError) as cm:
                parse_unit(bad)
            self.assertEqual(cm.exception.suggestion, want, bad)

    def test_currency_is_a_dimension(self):
        usd = parse_unit("USD")
        self.assertNotEqual(usd.dim, DIMENSIONLESS)
        self.assertEqual(dim_div(usd.dim, usd.dim), DIMENSIONLESS)


if __name__ == "__main__":
    unittest.main()
