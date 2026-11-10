# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Cost model calibration from journals (run 2)."""

import os
import tempfile
import unittest

from tests import fixtures as fx

from fis.config import Config
from fis import calib


def _ts(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "2026-11-01T%02d:%02d:%02dZ" % (h, m, s)


def _sysroute():
    cfg = Config()
    cfg.plugin_dir = fx.PLUGIN_DIR
    cfg.use_plugin_path()
    from fis import model
    return model.plugin().sysroute


class MeasureTest(unittest.TestCase):
    def test_brackets(self):
        ev = [
            {"timestamp": _ts(0), "event": "FSDJump", "SystemAddress": 1},
            # first leg after the jump: holds honk/FSS - NOT a travel sample
            {"timestamp": _ts(200), "event": "SupercruiseExit", "SystemAddress": 1,
             "Body": "A 1", "BodyID": 5},
            {"timestamp": _ts(210), "event": "SAAScanComplete", "SystemAddress": 1,
             "BodyName": "A 1"},
            # body-to-body hop A 1 -> A 2: this is the travel sample
            {"timestamp": _ts(300), "event": "SupercruiseEntry", "SystemAddress": 1},
            {"timestamp": _ts(400), "event": "SupercruiseExit", "SystemAddress": 1,
             "Body": "A 2", "BodyID": 6},
            {"timestamp": _ts(550), "event": "SAAScanComplete", "SystemAddress": 1,
             "BodyName": "A 2"},
            {"timestamp": _ts(600), "event": "ScanOrganic", "ScanType": "Log",
             "SystemAddress": 1, "Body": 6, "Species": "x"},
            {"timestamp": _ts(700), "event": "ScanOrganic", "ScanType": "Sample",
             "SystemAddress": 1, "Body": 6, "Species": "x"},
            {"timestamp": _ts(800), "event": "ScanOrganic", "ScanType": "Analyse",
             "SystemAddress": 1, "Body": 6, "Species": "x"},
        ]
        seen = []

        def leg(id64, a, b, at):
            seen.append((a, b))
            return 1000.0

        m = calib.measure(ev, leg)
        self.assertEqual(m.sc, [(1000.0, 100.0)])
        self.assertEqual(seen, [("A 1", "A 2")])
        # first DSS (10 s) is too short for the arrival bracket and has no
        # previous mapping; second: 150 s after arrival
        self.assertEqual(m.dss, [150.0])
        self.assertEqual(m.bio, [200.0])

    def test_fit_needs_enough_samples(self):
        sr = _sysroute()
        m = calib.Measurements()
        self.assertIs(calib.fit(sr, m), sr.DEFAULT_MODEL)
        m.dss = [120.0] * 6
        # plugin 4.3 fits only with >= 20 legs of 100 LS or more
        m.sc = [(d, 60 + 5 * d ** 0.5) for d in range(150, 5000, 200)]
        cm = calib.fit(sr, m)
        self.assertIsNot(cm, sr.DEFAULT_MODEL)
        self.assertEqual(round(cm.dss), 120)
        self.assertAlmostEqual(cm.k, 5.0, delta=0.6)

    def test_calibrator_reads_folder(self):
        sr = _sysroute()
        with tempfile.TemporaryDirectory() as d:
            lines = ['{"timestamp":"%s","event":"FSDJump","SystemAddress":1}' % _ts(0),
                     '{"timestamp":"%s","event":"SupercruiseExit","SystemAddress":1,'
                     '"Body":"B0","BodyID":2}' % _ts(100)]
            t = 100
            for i in range(24):        # plugin 4.3 needs >= 20 legs
                dist = 400 + 100 * i
                t += 60
                lines.append('{"timestamp":"%s","event":"SupercruiseEntry","SystemAddress":1}' % _ts(t))
                t += int(50 + 6 * dist ** 0.5)
                lines.append('{"timestamp":"%s","event":"SupercruiseExit","SystemAddress":1,'
                             '"Body":"B%d","BodyID":2}' % (_ts(t), i + 1))
            with open(os.path.join(d, "Journal.2026-11-01T000000.01.log"), "w") as f:
                f.write("\n".join(lines) + "\n")
            dists = {"B%d" % (i + 1): 400.0 + 100 * i for i in range(24)}
            c = calib.Calibrator(d, sr, lambda sysid, a, b, at: dists.get(b))
            self.assertIs(c.model, sr.DEFAULT_MODEL)
            c.run_once()
            self.assertEqual(c.info["measured"]["sc"], 24)
            self.assertTrue(c.info["calibrated"])
            self.assertIn("k", c.info["model"])


if __name__ == "__main__":
    unittest.main()
