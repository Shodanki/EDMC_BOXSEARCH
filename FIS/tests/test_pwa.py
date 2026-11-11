# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M12: the FIS as an installed app on the game PC - manifest and icon."""

import json
import os
import threading
import urllib.request

from fis.server import App, make_server
from tests.test_api import _Base, fed_tracker

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class TestPwa(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_manifest_served_and_installable(self):
        with urllib.request.urlopen(self.base + "/manifest.webmanifest", timeout=5) as r:
            self.assertEqual(r.headers.get("Content-Type"), "application/manifest+json")
            m = json.loads(r.read())
        # what Chrome / Edge need to offer "install": name, start_url, display, an icon
        self.assertEqual((m["name"], m["start_url"], m["display"]), ("SHBOX FIS", "/", "standalone"))
        icon = m["icons"][0]
        with urllib.request.urlopen(self.base + icon["src"], timeout=5) as r:
            self.assertEqual(r.headers.get("Content-Type"), "image/svg+xml")
            self.assertIn(b"<svg", r.read())

    def test_no_service_worker(self):
        # nothing cached: an FIS update must be live at the next reload
        for root, _d, files in os.walk(WEB):
            for f in files:
                if f.endswith(".js"):
                    with open(os.path.join(root, f), encoding="utf-8") as fh:
                        self.assertNotIn("serviceWorker.register", fh.read(), f)

    def test_manifest_only_on_this_pc(self):
        with open(os.path.join(WEB, "js", "app.js"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)', src)
        with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
            self.assertNotIn('rel="manifest"', fh.read())           # never for the tablet
