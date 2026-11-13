# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""N5 (4.11): one Python minimum (3.11, for tomllib) everywhere, and the start
scripts find Python without a path from the developer's PC."""

import os
import re
import unittest

import fis

FIS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestStart(unittest.TestCase):
    def test_python_minimum(self):
        self.assertEqual(fis.MIN_PYTHON, (3, 11))
        self.assertEqual(fis.python_problem((3, 11, 0)), "")
        self.assertEqual(fis.python_problem((3, 14, 2)), "")
        msg = fis.python_problem((3, 10, 12))
        self.assertIn("3.11 or newer", msg)
        self.assertIn("3.10", msg)
        self.assertEqual(fis.python_problem(), "")          # the one running these tests

    def test_start_scripts(self):
        for name in ("start_fis.bat", "fis_settings.bat"):
            with open(os.path.join(FIS_DIR, name), encoding="utf-8") as fh:
                bat = fh.read()
            self.assertNotRegex(bat, r"Python3\d\d", name)          # no one PC's install
            self.assertNotIn("3.10", bat, name)
            order = [bat.index(s) for s in ('set "PY=py -3"', "Python3*", 'set "PY=python"')]
            self.assertEqual(order, sorted(order), name + ": py launcher, own install, PATH")
        with open(os.path.join(FIS_DIR, "start_fis.bat"), encoding="utf-8") as fh:
            self.assertRegex(fh.read(), re.escape("Needs Python 3.11+"))


if __name__ == "__main__":
    unittest.main()
