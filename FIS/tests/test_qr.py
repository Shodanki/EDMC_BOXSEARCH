# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""E1: QR code of the home-network address on the settings page."""

import os
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from fis import qr, setup
from fis.server import App, Handler, make_server
from fis.vendor.qrcodegen import QrCode

from .test_api import _Base, fed_tracker

SVG_NS = "{http://www.w3.org/2000/svg}"


def modules_from_svg(text):
    """Read the dark modules back out of our SVG path (x, y without border)."""
    root = ET.fromstring(text)
    path = root.find(SVG_NS + "path")
    dark = set()
    for cmd in path.get("d").split():
        x, y = cmd[1:].split("h")[0].split(",")
        dark.add((int(x) - qr.BORDER, int(y) - qr.BORDER))
    return root, dark


class TestQrSvg(unittest.TestCase):
    def test_well_formed_and_content(self):
        text = "http://192.168.178.20:8765/?token=AbC_-123"
        root, dark = modules_from_svg(qr.svg(text))
        self.assertEqual(root.tag, SVG_NS + "svg")
        code = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
        n = code.get_size()
        self.assertEqual(root.get("viewBox"), "0 0 %d %d" % (n + 8, n + 8))
        want = {(x, y) for y in range(n) for x in range(n) if code.get_module(x, y)}
        self.assertEqual(dark, want)

    def test_vendor_kept_licence_and_source(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vend = os.path.join(here, "fis", "vendor")
        with open(os.path.join(vend, "qrcodegen.py"), encoding="utf-8") as fh:
            head = fh.read(1500)
        self.assertIn("Copyright (c) Project Nayuki. (MIT License)", head)
        self.assertIn("Permission is hereby granted", head)
        with open(os.path.join(vend, "SOURCE.md"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("nayuki.io", src)
        self.assertIn("MIT", src)


class TestQrEndpoint(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cfg.lan = True
        cls.cfg.token = "qr-token"
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.cfg.port = cls.srv.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.cfg.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.cfg.lan = False
        cls.cfg.token = ""

    def _get(self, q=""):
        return urllib.request.urlopen(self.base + "/api/settings/qr?token=qr-token" + q, timeout=5)

    def test_svg_is_the_address(self):
        with self._get() as r:
            self.assertTrue(r.headers["Content-Type"].startswith("image/svg+xml"))
            body = r.read().decode("utf-8")
        urls = setup.lan_urls(self.cfg.port, self.cfg.token)
        self.assertEqual(body, qr.svg(urls[0]))
        self.assertIn("token=qr-token", urls[0])
        ET.fromstring(body)
        # another address of the list, and a wrong index falls back to the first
        with self._get("&i=%d" % (len(urls) - 1)) as r:
            self.assertEqual(r.read().decode("utf-8"), qr.svg(urls[-1]))
        with self._get("&i=99") as r:
            self.assertEqual(r.read().decode("utf-8"), qr.svg(urls[0]))

    def test_needs_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/settings/qr", timeout=5)
        self.assertEqual(cm.exception.code, 401)
        cm.exception.close()

    def test_refused_from_lan(self):
        old = Handler.LOCAL
        Handler.LOCAL = ()          # every caller now looks like a LAN device
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self._get()
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()
        finally:
            Handler.LOCAL = old


class TestNewToken(_Base):
    """E15: a new access token from the settings page locks out the old one."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cfg.lan = True
        cls.cfg.token = "old-token"
        cls.cfg.ini_path = os.path.join(cls.tmp, "fis.ini")
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.cfg.port = cls.srv.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.cfg.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_renew(self):
        import json
        req = urllib.request.Request(self.base + "/api/settings", data=json.dumps({"new_token": True}).encode(),
                                     headers={"Content-Type": "application/json", "X-FIS-Settings": "1",
                                              "Origin": self.base}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        self.assertTrue(d["token_changed"])
        new = self.cfg.token
        self.assertNotEqual(new, "old-token")
        self.assertIn("token=" + new, d["lan_urls"][0])
        with open(self.cfg.ini_path, encoding="utf-8") as fh:
            self.assertIn(new, fh.read())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/health?token=old-token", timeout=5)
        self.assertEqual(cm.exception.code, 401)
        cm.exception.close()
        with urllib.request.urlopen(self.base + "/api/health?token=" + new, timeout=5) as r:
            self.assertEqual(r.status, 200)
        # without the settings header nobody can renew it
        req2 = urllib.request.Request(self.base + "/api/settings", data=b'{"new_token": true}',
                                      headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req2, timeout=5)
        self.assertEqual(cm.exception.code, 403)
        cm.exception.close()
        self.assertEqual(self.cfg.token, new)


class TestLanBrake(_Base):
    """E14: requests from home-network devices are braked, the game PC never."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cfg.lan = True
        cls.cfg.token = "brake-token"
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.saved = (Handler.LOCAL, Handler.RATE_MAX, Handler.FAIL_MAX)
        for d in (Handler._hits, Handler._fails, Handler._blocked):
            d.clear()

    def tearDown(self):
        Handler.LOCAL, Handler.RATE_MAX, Handler.FAIL_MAX = self.saved
        for d in (Handler._hits, Handler._fails, Handler._blocked):
            d.clear()

    def _code(self, q="?token=brake-token"):
        try:
            with urllib.request.urlopen(self.base + "/api/health" + q, timeout=5) as r:
                return r.status, None
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After")
            e.close()
            return e.code, ra

    def test_rate(self):
        Handler.LOCAL, Handler.RATE_MAX = (), 5     # every caller is a LAN device now
        codes = [self._code()[0] for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])
        code, ra = self._code()
        self.assertEqual(code, 429)
        self.assertGreaterEqual(int(ra), 1)

    def test_wrong_tokens_block(self):
        Handler.LOCAL, Handler.FAIL_MAX = (), 3
        self.assertEqual([self._code("?token=x")[0] for _ in range(3)], [401, 401, 401])
        self.assertEqual(self._code()[0], 429)      # blocked now, even with the right token

    def test_game_pc_never_braked(self):
        Handler.RATE_MAX, Handler.FAIL_MAX = 2, 2
        codes = [self._code()[0] for _ in range(5)] + [self._code("?token=x")[0] for _ in range(3)]
        self.assertEqual(codes, [200] * 5 + [401] * 3)
        self.assertEqual(self._code()[0], 200)


if __name__ == "__main__":
    unittest.main()
