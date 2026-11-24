# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""id64 beyond 2^53 leaves the FIS as text and comes back as text (5.1.0)."""

import json
import os
import unittest

from fis.jsonsafe import MAX_SAFE, as_id64, dumps, safe

BIG = 2 ** 54 + 3              # an a-boxel address with a large N2 can get here


class JsonSafeTest(unittest.TestCase):
    def test_only_large_ints_become_text(self):
        obj = {"id64": BIG, "small": 10477373803, "flag": True, "f": 2.5, "neg": -BIG,
               "list": [1, BIG, {"system_id64": BIG}], "tup": (BIG,), "s": "x"}
        out = safe(obj)
        self.assertEqual(out["id64"], str(BIG))
        self.assertEqual(out["neg"], str(-BIG))
        self.assertEqual(out["list"], [1, str(BIG), {"system_id64": str(BIG)}])
        self.assertEqual(out["tup"], [str(BIG)])
        self.assertIs(out["flag"], True)
        self.assertEqual((out["small"], out["f"], out["s"]), (10477373803, 2.5, "x"))
        self.assertEqual(obj["id64"], BIG, "the input is not changed")
        same = {"a": [1, 2, {"b": MAX_SAFE}]}
        self.assertIs(safe(same), same, "nothing to change: the same object, no copy")
        # what JavaScript reads back is exact
        self.assertEqual(json.loads(json.dumps(safe({"id": BIG})))["id"], str(BIG))

    def test_ids_coming_back(self):
        self.assertEqual(as_id64(BIG), BIG)
        self.assertEqual(as_id64(str(BIG)), BIG)
        self.assertEqual(as_id64(10477373803), 10477373803)
        for bad in (True, -5, "12a", "", None, 1.5, "9" * 21, str(2 ** 64), "1", str(MAX_SAFE)):
            self.assertIsNone(as_id64(bad), bad)

    def test_server_uses_it(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fis", "server.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('body = jsonsafe.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)', src)
        self.assertIn("payload = jsonsafe.dumps(data, ensure_ascii=False, default=str)", src)
        self.assertIn("sid = as_id64(h.get(\"id64\")) if isinstance(h, dict) else None", src)

    def test_dumps_fast_path(self):
        small = {"id64": 10477373803, "name": "Col 285 Sector"}
        self.assertEqual(dumps(small), json.dumps(small))
        self.assertEqual(json.loads(dumps({"id64": BIG}))["id64"], str(BIG))
        self.assertEqual(json.loads(dumps({"t": "1234567890123456789"}))["t"], "1234567890123456789",
                         "digits in a string stay as they are")


if __name__ == "__main__":
    unittest.main()
