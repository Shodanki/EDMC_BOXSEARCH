"""Science report: the rules that turn a datasheet into report facts."""

import unittest

from fis import science


def ids(rep):
    return [f["id"] for f in rep]


PLANET = {
    "kind": "Planet", "cls": "High metal content body", "radius_km": 3200.0, "mass_em": 0.4,
    "gravity_g": 2.4, "temp_k": 900.0, "landable": True, "terraform": "Terraformable",
    "atmosphere": "thin sulphur dioxide atmosphere", "atmo_type": "SulphurDioxide", "pressure_atm": 0.01,
    "volcanism": "", "tidal_lock": True, "flags": {"first": True, "first_map": True, "mapped": False},
    "materials": [["Iron", 20.0], ["Carbon", 15.0], ["Germanium", 5.0], ["Vanadium", 4.0],
                  ["Cadmium", 1.0], ["Niobium", 1.0], ["Polonium", 0.6]],
    "bio": {"signals": 2, "geo": 1, "genera": ["Bacterium", "Stratum"],
            "species": [{"species": "Bacterium Acies", "genus": "Bacterium"}], "prediction": []},
    "rings": [], "hotspots": [], "parent": "1",
}


class ScienceTest(unittest.TestCase):
    def test_planet_facts(self):
        rep = science.body_report(PLANET)
        got = ids(rep)
        for want in ("planet", "orbits", "terraformable", "first_discovery", "first_mapped",
                     "atmosphere", "tidal_lock", "geo_signals", "bio_signals", "bio_open",
                     "rare_materials", "jumponium_standard", "gravity_high", "hot", "toxic",
                     "dss_recommended", "landing", "sample"):
            self.assertIn(want, got)
        open_g = [f for f in rep if f["id"] == "bio_open"][0]
        self.assertEqual(open_g["v"]["g"], "Stratum")          # Bacterium already analysed
        self.assertEqual(science.worst(rep), "warn")
        # sections come in reading order
        order = [f["section"] for f in rep]
        self.assertLess(order.index("class"), order.index("hazards"))
        self.assertLess(order.index("hazards"), order.index("advice"))

    def test_very_high_gravity_is_danger(self):
        rep = science.body_report(dict(PLANET, gravity_g=3.5))
        self.assertIn("gravity_very_high", ids(rep))
        self.assertEqual(science.worst(rep), "danger")

    def test_premium_jumponium(self):
        mats = [["Carbon", 1], ["Germanium", 1], ["Arsenic", 1], ["Niobium", 1], ["Yttrium", 1], ["Polonium", 1]]
        self.assertIn("jumponium_premium", ids(science.body_report(dict(PLANET, materials=mats))))

    def test_star(self):
        rep = science.body_report({"kind": "Star", "star": {"type": "N", "subclass": 0, "luminosity": "VII",
                                                           "mass_sol": 1.4, "age_my": 100, "scoopable": False},
                                   "flags": {}, "bio": {}})
        self.assertEqual(ids(rep)[0], "star")
        self.assertIn("neutron", ids(rep))
        self.assertIn("not_scoopable", ids(rep))
        self.assertNotIn("landing", ids(rep))

    def test_quiet_rock(self):
        rep = science.body_report({"kind": "Planet", "cls": "Rocky body", "gravity_g": 0.1, "temp_k": 200,
                                   "landable": True, "flags": {"mapped": True}, "bio": {}, "materials": []})
        self.assertIn("no_atmosphere", ids(rep))
        self.assertIn("no_volcanism", ids(rep))
        self.assertNotIn("dss_recommended", ids(rep))
        self.assertEqual(science.worst(rep), "info")


class SystemReportTest(unittest.TestCase):
    def test_system(self):
        g = science.G
        rows = [
            {"body_id": 0, "name": "Sys A", "kind": "Star", "star_type": "N", "was_discovered": 1},
            {"body_id": 1, "name": "Sys A 1", "kind": "Planet", "planet_class": "Water world", "parent_id": 0,
             "was_discovered": 0, "sig_bio": 3, "organics": 1, "mapped": 0, "radius": 6.0e6, "sma": 1e11, "ecc": 0.9},
            {"body_id": 2, "name": "Sys A 1 a", "kind": "Planet", "planet_class": "Rocky body", "parent_id": 1,
             "landable": 1, "radius": 1.0e6, "sma": 1.5e7, "ecc": 0.0, "period": 3600, "gravity": 2.5 * g,
             "atmosphere": "thin neon atmosphere"},
            {"body_id": 3, "name": "Sys A 1 a a", "kind": "Planet", "planet_class": "Icy body", "parent_id": 2},
        ]
        sys_out = {"name": "Sys A", "body_count": 4, "fss_complete": True,
                   "bodies": [{"body_id": 1, "flags": {"wants_dss": True}}]}
        rep = science.system_report(rows, sys_out)
        got = ids(rep)
        for want in ("sys_bodies", "sys_fss_done", "sys_first", "sys_valuable", "sys_bio", "sys_eccentric",
                     "sys_fast_orbit", "sys_close", "sys_nested", "sys_landable_atmo", "sys_neutron", "sys_heavy",
                     "sys_next_dss"):
            self.assertIn(want, got)
        close = [f for f in rep if f["id"] == "sys_close"][0]
        self.assertEqual(close["v"]["list"], "1 a")           # 15 000 km from the centre of a 6000 km planet
        self.assertEqual([f for f in rep if f["id"] == "sys_nested"][0]["v"]["list"], "1 a a")


class BoostTest(unittest.TestCase):
    def test_boost_kind(self):
        from fis import model
        self.assertEqual(model.boost_kind("N"), "neutron")
        for wd in ("D", "DA", "DAB", "DC", "DQ"):
            self.assertEqual(model.boost_kind(wd), "white_dwarf")
        for other in ("M", "K", "H", "DoesNotExist", None):
            self.assertIsNone(model.boost_kind(other))


if __name__ == "__main__":
    unittest.main()
