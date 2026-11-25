# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M15: the start banner says what the FIS does - it writes its own files."""

import os
import unittest


class BannerTest(unittest.TestCase):
    def test_banner_is_true(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fis", "server.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("writes nothing", src)
        self.assertIn("reads the game's files, sends nothing to the game, writes only its own", src)


if __name__ == "__main__":
    unittest.main()
