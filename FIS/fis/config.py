# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Paths, port, language and LAN token. Values come from fis.ini, otherwise defaults.

fis.ini is written by the first-start dialogue (fis/setup.py); the user never
needs command-line parameters."""

from __future__ import annotations

import configparser
import os
import secrets
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INI_PATH = os.path.join(ROOT, "fis.ini")
WEB_DIR = os.path.join(ROOT, "web")

_LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
DEFAULT_DB = os.path.join(_LOCAL, "EDMarketConnector", "plugins", "SHBOXSEARCH",
                          "shboxsearch.sqlite")
DEFAULT_JOURNAL = os.path.join(os.path.expanduser("~"), "Saved Games",
                               "Frontier Developments", "Elite Dangerous")
# The plugin source the FIS imports its maths from (sysroute, biopredict ...).
# Shipped inside the plugin as SHBOXSEARCH/FIS, so normally the parent folder.
_PARENT = os.path.dirname(ROOT)
DEFAULT_PLUGIN = (_PARENT if os.path.exists(os.path.join(_PARENT, "load.py"))
                  else os.path.join(_PARENT, "SHBOXSEARCH"))

DEFAULT_PORT = 8770
# Same default as the plugin: "DSS or bio still open"
DEFAULT_FILTERS = "todo"
# EDMC's own settings file - the plugin's route filters live there
EDMC_CONFIG = os.path.join(_LOCAL, "EDMarketConnector", "config.toml")
PLUGIN_FILTERS = ("all", "new", "unmapped", "signals", "landable", "valuable", "rings", "todo")
LANGUAGES = ("en", "de")


def _bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _path(raw: str) -> str:
    """Expand %VARS% and ~; relative paths count from the FIS folder."""
    p = os.path.expanduser(os.path.expandvars(raw.strip()))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(ROOT, p))


class Config:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = DEFAULT_PORT
        self.lan = False
        self.token = ""
        self.db_path = DEFAULT_DB
        self.journal_dir = DEFAULT_JOURNAL
        self.plugin_dir = DEFAULT_PLUGIN
        self.route_filters = DEFAULT_FILTERS
        # "plugin": the route uses the filters set in the plugin (EDMC settings),
        # so FIS and plugin show the same stops; "ini": route_filters below
        self.route_source = "plugin"
        self.edmc_config = EDMC_CONFIG
        self._pf_cache = None
        self.language = "en"        # browser default; each browser may switch
        self.open_browser = True
        self.setup_done = False     # first-start questions answered
        self.firewall = ""          # "", "ok" or "declined" (LAN rule offer)
        self.poll_s = 0.5
        self.ini_path = INI_PATH
        self.main_cmdr = ""         # C1: FID of the main commander, "" = automatic

    @property
    def filters(self) -> List[str]:
        if self.route_source == "plugin":
            pf = self.plugin_filters()
            if pf:
                return pf
        return [f.strip() for f in self.route_filters.split(",") if f.strip()]

    def _plugin_settings(self) -> Optional[Dict[str, Any]]:
        """The plugin's settings in EDMC's config.toml - read only, cached
        while the file is unchanged. None if not readable."""
        try:
            st = os.stat(self.edmc_config)
        except OSError:
            return None
        sig = (st.st_mtime, st.st_size)
        if self._pf_cache and self._pf_cache[0] == sig:
            return self._pf_cache[1]
        try:
            import tomllib
            with open(self.edmc_config, "rb") as fh:
                data = tomllib.load(fh)
        except Exception:
            return None
        # EDMC 6 keeps everything under [settings]; older files at the top level
        if isinstance(data.get("settings"), dict):
            data = data["settings"]
        self._pf_cache = (sig, data)
        return data

    def plugin_filters(self) -> Optional[List[str]]:
        """
        The plugin's route filters, combined like the plugin does: "route
        every body" wins, otherwise the chosen filters, otherwise "still
        outstanding". None if EDMC's config is not readable.
        """
        data = self._plugin_settings()
        if data is None:
            return None
        if str(data.get("shboxsearch_route_all", "")).lower() in ("true", "1"):
            return ["all"]
        raw = str(data.get("shboxsearch_filters", "") or "")
        return [f.strip() for f in raw.split(",") if f.strip() in PLUGIN_FILTERS] or ["todo"]

    @property
    def skip_arrival(self) -> bool:
        """R2: the plugin's "start the route at the arrival star" switched
        off - the route then starts with the first planned body."""
        data = self._plugin_settings() if self.route_source == "plugin" else None
        return str((data or {}).get("shboxsearch_route_arrival", "true")).lower() in ("false", "0")

    # ------------------------------------------------------------------ ini
    def load(self, path: Optional[str] = None) -> "Config":
        path = path or self.ini_path
        self.ini_path = path
        cp = configparser.ConfigParser(interpolation=None)
        if os.path.exists(path):
            cp.read(path, encoding="utf-8")
        s = cp["fis"] if cp.has_section("fis") else {}
        self.port = int(s.get("port", self.port))
        self.lan = _bool(s.get("lan", "false"))
        self.token = (s.get("token", "") or "").strip()
        self.db_path = _path(s.get("db_path", "") or self.db_path)
        self.journal_dir = _path(s.get("journal_dir", "") or self.journal_dir)
        self.plugin_dir = _path(s.get("plugin_dir", "") or self.plugin_dir)
        self.route_filters = s.get("route_filters", self.route_filters) or DEFAULT_FILTERS
        src = (s.get("route_source", "") or "plugin").strip().lower()
        self.route_source = src if src in ("plugin", "ini") else "plugin"
        lang = (s.get("language", "") or "").strip().lower()
        self.language = lang if lang in LANGUAGES else "en"
        self.open_browser = _bool(s.get("open_browser", "true"))
        self.setup_done = _bool(s.get("setup_done", "false"))
        self.firewall = (s.get("firewall", "") or "").strip().lower()
        self.main_cmdr = (s.get("main_cmdr", "") or "").strip()
        if self.lan:
            self.host = "0.0.0.0"
        return self

    def ensure_token(self, save: bool = True) -> bool:
        """Create a random LAN token (stored in fis.ini). True if new."""
        if self.token:
            return False
        self.token = secrets.token_urlsafe(18)
        if save:
            self.save()
        return True

    def new_token(self) -> str:
        """E15: replace the LAN token (a device that should no longer get in,
        a token that was shown on stream). Every device needs the new
        address once; the caller saves."""
        old = self.token
        while self.token == old:
            self.token = secrets.token_urlsafe(18)
        return self.token

    def save(self) -> None:
        """Write fis.ini: the dialogue's answers plus whatever else was set.
        Keys the FIS does not know are kept."""
        cp = configparser.ConfigParser(interpolation=None)
        if os.path.exists(self.ini_path):
            cp.read(self.ini_path, encoding="utf-8")
        if not cp.has_section("fis"):
            cp.add_section("fis")
        vals = {
            "language": self.language, "port": str(self.port),
            "lan": "true" if self.lan else "false", "token": self.token,
            "open_browser": "true" if self.open_browser else "false",
            "setup_done": "true" if self.setup_done else "false",
            "firewall": self.firewall, "route_filters": self.route_filters,
            "route_source": self.route_source, "main_cmdr": self.main_cmdr,
        }
        for k, v in vals.items():
            cp.set("fis", k, v)
        for k, v, d in (("db_path", self.db_path, DEFAULT_DB),
                        ("journal_dir", self.journal_dir, DEFAULT_JOURNAL),
                        ("plugin_dir", self.plugin_dir, DEFAULT_PLUGIN)):
            if os.path.normcase(os.path.normpath(v)) != os.path.normcase(os.path.normpath(d)):
                cp.set("fis", k, v)
        with open(self.ini_path, "w", encoding="utf-8") as fh:
            fh.write("; SHBOX FIS settings - written by the first-start dialogue.\n"
                     "; Change them on the settings page (gear at the bottom of the FIS, on this PC),\n"
                     "; with fis_settings.bat, or by hand.\n\n")
            cp.write(fh)

    def use_plugin_path(self) -> None:
        """Make the plugin's pure modules importable (sysroute, biopredict ...)."""
        if self.plugin_dir and self.plugin_dir not in sys.path:
            # appended, never prepended: plugin files must not shadow stdlib
            sys.path.append(self.plugin_dir)
