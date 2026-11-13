# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Test helper: import the plugin the way EDMC does - as a package, so that
``load`` and its sibling modules use their relative imports.

EDMC puts its plugins folder on sys.path and imports "<folder>.load". The
checkout folder may have any name (EDMC_BOXSEARCH in CI), so the package is
registered under the plugin's own name, SHBOXSEARCH, pointing at the
checkout.

    import plugin_pkg
    load = plugin_pkg.import_plugin()          # EDMC modules stubbed first
    from SHBOXSEARCH import planning, panel
    plugin_pkg.use_settings(cfg)               # EDMC config reads/writes cfg
"""
import importlib
import importlib.machinery
import importlib.util
import os
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "SHBOXSEARCH"
EDMC_MODULES = ("config", "theme", "myNotebook", "monitor", "l10n", "companion", "plug",
                "EDMCLogging", "ttkHyperlinkLabel")


def stub_edmc(tk: bool = True) -> None:
    """Replace EDMC's modules by mocks; without Tk (CI images) Tk as well."""
    for m in EDMC_MODULES:
        sys.modules.setdefault(m, mock.MagicMock())
    if tk:
        try:                                  # CI images may lack Tk; no window is opened
            import tkinter  # noqa: F401
        except ImportError:
            for m in ("tkinter", "tkinter.filedialog", "tkinter.ttk"):
                sys.modules[m] = mock.MagicMock()


def import_plugin(stub: bool = True):
    """Register the checkout as package SHBOXSEARCH and import its load.py."""
    if stub:
        stub_edmc()
    if PKG not in sys.modules:
        spec = importlib.machinery.ModuleSpec(PKG, None, is_package=True)
        spec.submodule_search_locations = [ROOT]
        sys.modules[PKG] = importlib.util.module_from_spec(spec)
    return importlib.import_module(PKG + ".load")


def use_settings(cfg: dict) -> None:
    """Let the stubbed EDMC config read and write the dict ``cfg``, so the
    plugin's own cfg_* helpers run unchanged in the tests."""
    from config import config
    config.get_bool.side_effect = lambda k, default=False: cfg.get(k, default)
    config.get_int.side_effect = lambda k, default=0: cfg.get(k, default)
    config.get_str.side_effect = lambda k, default="": cfg.get(k, default)
    config.get.side_effect = lambda k, default=None: cfg.get(k, default)
    config.set.side_effect = lambda k, v: cfg.__setitem__(k, v)
