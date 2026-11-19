# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""ui.meter() (5.0 TH1) and ui.blinkFor() (user 18.11.: alarms blink only at their onset) under Node: the share 0-100 on the element (--p, data-p,
aria) and the plain bar inside, clamped; nonsense gives 0. Skipped without Node."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js")
NODE = shutil.which("node")

SCRIPT = r"""
import fs from "fs";
// a minimal DOM: what el() touches
class N { constructor(t) { this.tag = t; this.attrs = {}; this.kids = []; this.style = {}; this.className = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); } append(...k) { this.kids.push(...k); } addEventListener() {} }
globalThis.Node = N;
globalThis.document = { createElement: (t) => new N(t), createTextNode: (s) => ({ text: s }) };
const code = fs.readFileSync(process.argv[2], "utf8").replace(/^import .*i18n\.js";$/m,
  'const t = (s) => s, locale = () => "en", lang = () => "en";');
fs.writeFileSync(process.argv[3], code);
const ui = await import(new URL("file:///" + process.argv[3].replace(/\\/g, "/")).href);
const cases = [[41, 100], [5, 20], [150, 100], [-3, 100], ["x", 100], [3, 0]];
const out = cases.map(([v, m]) => { const n = ui.meter(v, m);
  return { pct: ui.meterPct(v, m), cls: n.className, style: n.attrs.style, p: n.attrs["data-p"], now: n.attrs["aria-valuenow"],
    role: n.attrs.role, bar: n.kids[0].attrs.style }; });
const b = [ui.blinkFor("a", true, 8, 1000), ui.blinkFor("a", true, 8, 4000), ui.blinkFor("a", true, 8, 9001),
  ui.blinkFor("a", false, 8, 9500), ui.blinkFor("a", true, 8, 20000), ui.blinkFor("b", false, 8, 1)];
console.log(JSON.stringify({ out, b }));
"""


@unittest.skipUnless(NODE, "Node not installed")
class MeterTest(unittest.TestCase):
    def test_share_on_the_element_and_the_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, mod = os.path.join(tmp, "run.mjs"), os.path.join(JS, "_meter_test_ui.mjs")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(SCRIPT)
            try:
                res = subprocess.run([NODE, script, os.path.join(JS, "ui.js"), mod], capture_output=True, text=True,
                                     timeout=60)
            finally:
                if os.path.exists(mod):
                    os.remove(mod)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
        out = got["out"]
        self.assertEqual([o["pct"] for o in out], [41, 25, 100, 0, 0, 0])
        first = out[0]
        self.assertEqual((first["cls"], first["style"], first["p"], first["now"], first["role"], first["bar"]),
                         ("lbar meter", "--p: 41.0", "41", "41", "meter", "width: 41.0%"))
        self.assertEqual(out[2]["bar"], "width: 100.0%")
        # an alarm blinks from its onset for its seconds, a redraw runs on, off and on again starts anew
        self.assertEqual(got["b"], ["animation-delay: -0ms", "animation-delay: -3000ms", "", "", "animation-delay: -0ms", ""])


if __name__ == "__main__":
    unittest.main()
