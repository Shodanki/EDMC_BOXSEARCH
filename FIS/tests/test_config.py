"""fis.ini handling and the LAN token."""

import os
import tempfile
import unittest

from fis.config import ROOT, Config


class TestPluginFilters(unittest.TestCase):
    """The FIS routes with the plugin's own filters (EDMC config.toml, read only)."""

    def _cfg(self, toml):
        d = tempfile.mkdtemp()
        c = Config().load(os.path.join(d, "none.ini"))
        c.edmc_config = os.path.join(d, "config.toml")
        if toml is not None:
            with open(c.edmc_config, "w", encoding="utf-8") as fh:
                fh.write(toml)
        return c

    def test_route_every_body_wins(self):
        c = self._cfg('[settings]\nshboxsearch_route_all = true\nshboxsearch_filters = "new"\n')
        self.assertEqual(c.filters, ["all"])

    def test_chosen_filters(self):
        c = self._cfg('[settings]\nshboxsearch_route_all = false\nshboxsearch_filters = "new,signals,bogus"\n')
        self.assertEqual(c.filters, ["new", "signals"])

    def test_fallbacks(self):
        self.assertEqual(self._cfg('[settings]\nother = 1\n').filters, ["todo"])
        self.assertEqual(self._cfg(None).filters, ["todo"])          # no EDMC: fis.ini value
        c = self._cfg('[settings]\nshboxsearch_route_all = true\n')
        c.route_source, c.route_filters = "ini", "landable"
        self.assertEqual(c.filters, ["landable"])                    # explicitly fixed in fis.ini


class TestConfig(unittest.TestCase):
    def test_defaults_without_ini(self):
        d = tempfile.mkdtemp()
        c = Config().load(os.path.join(d, "none.ini"))
        c.edmc_config = os.path.join(d, "no-edmc.toml")      # not this PC's EDMC
        self.assertEqual((c.host, c.port, c.lan), ("127.0.0.1", 8770, False))
        self.assertEqual(c.route_source, "plugin")
        self.assertEqual(c.filters, ["todo"])

    def test_ini_values_and_relative_paths(self):
        d = tempfile.mkdtemp()
        ini = os.path.join(d, "fis.ini")
        with open(ini, "w", encoding="utf-8") as fh:
            fh.write("[fis]\nport = 9001\nlan = yes\nplugin_dir = ..\\SHBOXSEARCH\n"
                     "route_source = ini\nroute_filters = new, signals\n")
        c = Config().load(ini)
        self.assertEqual((c.port, c.lan, c.host), (9001, True, "0.0.0.0"))
        self.assertEqual(c.filters, ["new", "signals"])
        self.assertEqual(c.plugin_dir, os.path.normpath(os.path.join(ROOT, "..", "SHBOXSEARCH")))

    def test_env_vars_in_paths(self):
        d = tempfile.mkdtemp()
        ini = os.path.join(d, "fis.ini")
        with open(ini, "w", encoding="utf-8") as fh:
            fh.write("[fis]\ndb_path = %LOCALAPPDATA%\\x\\db.sqlite\n")
        c = Config().load(ini)
        self.assertTrue(c.db_path.startswith(os.environ.get("LOCALAPPDATA", "%LOCALAPPDATA%")))

    def test_token_created_once(self):
        d = tempfile.mkdtemp()
        ini = os.path.join(d, "fis.ini")
        c = Config().load(ini)
        self.assertTrue(c.ensure_token())
        tok = c.token
        self.assertGreaterEqual(len(tok), 20)
        c2 = Config().load(ini)
        self.assertEqual(c2.token, tok)
        self.assertFalse(c2.ensure_token())


if __name__ == "__main__":
    unittest.main()
