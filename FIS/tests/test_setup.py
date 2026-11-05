"""First start: questions once, answers in fis.ini; LAN firewall offer and addresses."""

import os
import tempfile
import unittest

from fis import setup
from fis.config import Config


def _answers(*vals):
    it = iter(vals)
    return lambda prompt="": next(it)


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ini = os.path.join(self.tmp.name, "fis.ini")
        self.out = []

    def tearDown(self):
        self.tmp.cleanup()

    def _cfg(self):
        c = Config().load(self.ini)
        c.db_path = os.path.join(self.tmp.name, "db.sqlite")
        open(c.db_path, "w").close()
        c.journal_dir = self.tmp.name
        return c

    def test_first_start_is_remembered(self):
        c = self._cfg()
        self.assertFalse(c.setup_done)
        # German, home network, no browser, default port
        setup.run_setup(c, inp=_answers("2", "2", "n", ""), out=self.out.append)
        c2 = Config().load(self.ini)
        self.assertTrue(c2.setup_done)
        self.assertEqual(c2.language, "de")
        self.assertTrue(c2.lan)
        self.assertEqual(c2.host, "0.0.0.0")
        self.assertFalse(c2.open_browser)
        self.assertEqual(c2.port, 8770)
        self.assertGreaterEqual(len(c2.token), 20)
        self.assertTrue(any("Heimnetz" in m for m in self.out))   # asked in German

    def test_defaults_on_enter(self):
        c = self._cfg()
        setup.run_setup(c, inp=_answers("", "", "", "8790"), out=self.out.append)
        c2 = Config().load(self.ini)
        self.assertEqual((c2.language, c2.lan, c2.open_browser, c2.port), ("en", False, True, 8790))
        self.assertEqual(c2.token, "")
        self.assertEqual(c2.host, "127.0.0.1")

    def test_unknown_language_falls_back(self):
        with open(self.ini, "w", encoding="utf-8") as fh:
            fh.write("[fis]\nlanguage = klingon\n")
        self.assertEqual(Config().load(self.ini).language, "en")

    def test_unknown_keys_survive_save(self):
        with open(self.ini, "w", encoding="utf-8") as fh:
            fh.write("[fis]\nmy_note = keep me\n")
        c = Config().load(self.ini)
        c.save()
        with open(self.ini, encoding="utf-8") as fh:
            self.assertIn("my_note = keep me", fh.read())


class FirewallTest(unittest.TestCase):
    EN = ("\nRule Name:                            Other\n----\nEnabled:                              Yes\n"
          "Protocol:                             UDP\nLocalPort:                            8770\n"
          "Action:                               Allow\n\n"
          "Rule Name:                            SHBOX FIS\n----\n"
          "Enabled:                              Yes\nDirection:                            In\n"
          "Profiles:                             Private\nProtocol:                             TCP\n"
          "LocalPort:                            8770\nAction:                               Allow\n")
    # German Windows, a rule made by hand under another name
    DE = ("Regelname:                               fis\n-----\nAktiviert:                               Ja\n"
          "Richtung:                                Eingehend\nProfile:                                 Dom\u00e4ne,Privat\n"
          "Protokoll:                               TCP\nLokaler Port:                            8770\n"
          "Aktion:                                  Zulassen\n")
    OFF = DE.replace("Aktiviert:                               Ja", "Aktiviert:                               Nein")
    BLOCK = DE.replace("Zulassen", "Blockieren")
    RANGE = DE.replace("Lokaler Port:                            8770", "Lokaler Port:                            8000-8999")

    def test_rule_parsing(self):
        self.assertEqual(setup.firewall_rule_ok(8770, run=lambda a: self.EN), "SHBOX FIS")
        self.assertEqual(setup.firewall_rule_ok(8770, run=lambda a: self.DE), "fis")
        self.assertEqual(setup.firewall_rule_ok(8770, run=lambda a: self.RANGE), "fis")
        self.assertEqual(setup.firewall_rule_ok(8771, run=lambda a: self.EN), "")
        self.assertEqual(setup.firewall_rule_ok(8770, run=lambda a: self.OFF), "")
        self.assertEqual(setup.firewall_rule_ok(8770, run=lambda a: self.BLOCK), "")
        self.assertEqual(setup.firewall_rule_ok(8770, run=lambda a: "No rules match the specified criteria."), "")
        self.assertIsNone(setup.firewall_rule_ok(8770, run=lambda a: None))

    def test_rule_is_narrow(self):
        cmd = " ".join(setup.firewall_rule_command(8770))
        for part in ("-Verb RunAs", "dir=in", "protocol=TCP", "localport=8770",
                     "profile=private", "remoteip=localsubnet", 'name="SHBOX FIS"'):
            self.assertIn(part, cmd)

    def _lan_cfg(self, tmp):
        c = Config().load(os.path.join(tmp, "fis.ini"))
        c.lan, c.token, c.setup_done = True, "tok", True
        return c

    def test_offer_once_then_respect_no(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._lan_cfg(tmp)
            made = []
            out = []
            setup.check_lan(c, inp=_answers("n"), out=out.append, interactive=True,
                            fw_ok=lambda p: "", fw_create=lambda p: made.append(p) or True)
            self.assertEqual(made, [])
            self.assertEqual(Config().load(c.ini_path).firewall, "declined")
            # next start: not asked again (no answer available would raise)
            c2 = Config().load(c.ini_path)
            c2.lan, c2.token = True, "tok"
            setup.check_lan(c2, inp=_answers(), out=out.append, interactive=True,
                            fw_ok=lambda p: "", fw_create=lambda p: made.append(p) or True)
            self.assertEqual(made, [])
            self.assertTrue(any("?token=tok" in o for o in out))

    def test_yes_creates_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._lan_cfg(tmp)
            made = []
            setup.check_lan(c, inp=_answers(""), out=lambda s: None, interactive=True,
                            fw_ok=lambda p: "", fw_create=lambda p: made.append(p) or True)
            self.assertEqual(made, [8770])
            self.assertEqual(Config().load(c.ini_path).firewall, "ok")

    def test_existing_rule_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._lan_cfg(tmp)
            setup.check_lan(c, inp=_answers(), out=lambda s: None, interactive=True,
                            fw_ok=lambda p: "fis",
                            fw_create=lambda p: self.fail("must not create"))

    def test_private_addresses_only(self):
        self.assertTrue(setup._private("192.168.1.20"))
        self.assertTrue(setup._private("10.0.0.5"))
        self.assertTrue(setup._private("172.20.1.1"))
        self.assertFalse(setup._private("8.8.8.8"))
        self.assertFalse(setup._private("127.0.0.1"))
        for u in setup.lan_urls(8770, ""):
            self.assertTrue(u.startswith("http://") and ":8770/" in u)


if __name__ == "__main__":
    unittest.main()
