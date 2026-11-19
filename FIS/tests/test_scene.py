# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SYSTEM map scaling (web/js/views/scene.js) under Node - test finding
own-5 (17.11.2026): near bodies were drawn too close. The case is built
after the real one (Synuefe DU-Z c16-19 C): star C 12 929 LS from the
arrival star, planet C 2 at 325 LS (radius 3 032 km) with its moon 0.315 LS
out, the barycentre of C 4 / C 5 at 529 LS in nearly the same direction.
SB1/SB2 (19.11.2026): replay of Synuefe AZ-K b27-1 - the brown dwarf B
163 000 LS out was drawn with B 5 beside A 8 (2 510 LS), and lit like a star.
Skipped without Node."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views")
NODE = shutil.which("node")


def _b(bid, short, kind, pos, ppos=None, parent=None, radius=None, group=None, colour="metal"):
    return {"body_id": bid, "short": short, "name": short, "kind": kind, "pos": pos, "ppos": ppos,
            "parent_id": parent, "radius_km": radius, "group": group, "moon": False, "rings": [],
            "colour": colour, "orbit": None, "pole": None, "flags": {}}


C = [12929.0, 0.0, 0.0]
SYS = {"bodies": [
    _b(0, "A", "Star", [0.0, 0.0, 0.0], radius=500000),
    _b(4, "C", "Star", C, [0.0, 0.0, 0.0], 0, 400000),
    _b(41, "C 2", "Planet", [C[0] + 325.0, 0.0, 0.0], C, 4, 3032, "C 2"),
    _b(42, "C 2 a", "Planet", [C[0] + 325.0, 0.315, 0.0], [C[0] + 325.0, 0.0, 0.0], 41, 900, "C 2"),
    _b(45, "C 4", "Planet", [C[0] + 529.0, 8.0, 0.0], C, 4, 2500, "C 4"),
    # a planet with evenly spaced moons (A 3 of Synuefe OW-V c18-2): the order and the steps stay
    _b(30, "P", "Planet", [1800.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0, 20000, "P"),
] + [_b(31 + i, "P " + "abcd"[i], "Planet", [1800.0, r, 0.0], [1800.0, 0.0, 0.0], 30, 1500, "P")
     for i, r in enumerate((1.73, 3.14, 4.73, 6.18))]}

# Synuefe AZ-K b27-1 as the FIS server sends it (LS, rounded): A and B around
# the unscanned barycentre 0, B a brown dwarf (L) 163 222 LS out
BARY = [49444.0, -12216.0, -19135.0]
BPOS = [148333.0, -36649.0, -57406.0]
AZK = {"bodies": [
    _b(1, "A", "Star", [0.0, 0.0, 0.0], BARY, 0, 325145, colour="star-m"),
    _b(2, "B", "Star", BPOS, BARY, 0, 240246, colour="star-l"),
    _b(3, "A 1", "Planet", [32.0, 87.0, 30.0], [0.0, 0.0, 0.0], 1, 8219, "A 1", "water"),
    _b(13, "A 8", "Planet", [1472.0, -1667.0, -1164.0], [0.0, 0.0, 0.0], 1, 5419, "A 8", "icy"),
    _b(19, "B 1", "Planet", [148040.0, -36710.0, -57350.0], BPOS, 2, 4810, "B 1", "icy"),
    _b(23, "B 5", "Planet", [145957.0, -37376.0, -57057.0], BPOS, 2, 4413, "B 5", "icy"),
    _b(24, "B 6", "Planet", [146515.0, -40383.0, -58484.0], BPOS, 2, 5140, "B 6", "icy"),
]}

SCRIPT = r"""
import fs from "fs";
const code = fs.readFileSync(process.argv[2], "utf8")
  .replace(/^import .*ui\.js";$/m, 'const fixLabel = (x) => x, C = {}, alpha = () => "";');
fs.writeFileSync(process.argv[3], code);
const { buildScene } = await import(new URL("file:///" + process.argv[3].replace(/\\/g, "/")).href);
const sys = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const out = {};
for (const mode of ["log", "lin"]) {
  const sc = buildScene(sys, mode);
  out[mode] = Object.fromEntries(sc.bodies.map((b) => [b.short,
    { p: b.p, size: b.size, glow: b.glow, far: b.far, colour: b.colour }]));
}
console.log(JSON.stringify(out));
"""


def _scene(system):
    """buildScene of scene.js under Node for one system: {mode: {short: body}}."""
    with tempfile.TemporaryDirectory() as d:
        js, sysf = os.path.join(d, "run.mjs"), os.path.join(d, "sys.json")
        with open(js, "w", encoding="utf-8") as fh:
            fh.write(SCRIPT)
        with open(sysf, "w", encoding="utf-8") as fh:
            json.dump(system, fh)
        res = subprocess.run([NODE, js, os.path.join(WEB, "scene.js"), os.path.join(d, "scene.mjs"), sysf],
                             capture_output=True, text=True, timeout=60)
        if res.returncode:
            raise AssertionError(res.stderr)
        return json.loads(res.stdout)


@unittest.skipUnless(NODE, "Node not installed")
class SceneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _scene(SYS)
        cls.azk = _scene(AZK)

    @staticmethod
    def _d(a, b):
        return sum((x - y) ** 2 for x, y in zip(a["p"], b["p"])) ** 0.5

    def test_moon_clear_of_its_planet(self):
        m = self.out["log"]
        gap = self._d(m["C 2"], m["C 2 a"]) - m["C 2"]["size"] - m["C 2 a"]["size"]
        self.assertGreater(gap, 0.6)                      # 0.25 up to 5.0-pre

    def test_groups_203_ls_apart_are_apart(self):
        m = self.out["log"]
        self.assertGreater(self._d(m["C 2 a"], m["C 4"]), 1.0)     # 0.51 up to 5.0-pre
        self.assertGreater(self._d(m["C 2"], m["C 4"]), 2.5)       # 325 -> 529 LS: 1.7 up to 5.0-pre

    def test_moons_keep_order_and_steps(self):
        m = self.out["log"]
        d = [self._d(m["P"], m["P " + c]) for c in "abcd"]
        self.assertEqual(d, sorted(d))
        steps = [b - a for a, b in zip(d, d[1:])]
        self.assertLess(max(steps) / min(steps), 1.3)              # still about even

    def test_linear_mode_unchanged(self):
        m = self.out["lin"]
        # linear: 60 units across the farthest body, nothing else
        far = max(sum(x * x for x in b["pos"]) ** 0.5 for b in SYS["bodies"])
        self.assertAlmostEqual(self._d(m["A"], m["C 2"]), (C[0] + 325.0) * 60 / far, places=3)

    def test_far_companion_group_clear_of_the_arrival_group(self):
        m = self.azk["log"]
        a = [v for k, v in m.items() if k.startswith("A")]
        b = [v for k, v in m.items() if k.startswith("B")]
        gap = min(self._d(x, y) - x["size"] - y["size"] for x in a for y in b)
        self.assertGreater(gap, 10.0)                              # B 5 / A 8: 2.8 up to 5.0-pre
        self.assertAlmostEqual(m["B"]["far"], 163222.0, delta=1.0)  # the label tells the true distance
        self.assertEqual(m["A"]["far"], 0)

    def test_far_companion_keeps_its_own_layout(self):
        m = self.azk["log"]
        rel = [self._d(m["B"], m[k]) for k in ("B 1", "B 5", "B 6")]
        self.assertEqual(rel, sorted(rel))                         # 296, 2 400, 4 400 LS from B
        self.assertGreater(self._d(m["B"], m["A"]), self._d(m["A 8"], m["A"]))

    def test_arrival_star_at_the_centre_of_its_planets(self):
        m = self.azk["log"]
        self.assertLess(max(abs(v) for v in m["A"]["p"]), 1e-6)    # 4.5 units off up to 5.0-pre

    def test_brown_dwarf_dark_and_dim(self):
        m = self.azk["log"]
        self.assertLess(m["B"]["glow"], 0.5)
        self.assertEqual(m["A"]["glow"], 1)
        lum = [sum(int(c["colour"][i:i + 2], 16) for i in (1, 3, 5)) for c in (m["A"], m["B"])]
        self.assertLess(lum[1], lum[0] * 0.75)                     # darker than the M star
        self.assertEqual(m["A 8"]["glow"], 0)


if __name__ == "__main__":
    unittest.main()
