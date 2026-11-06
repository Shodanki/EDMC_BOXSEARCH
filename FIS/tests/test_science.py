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


if __name__ == "__main__":
    unittest.main()
