# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The plugin's settings page (4.12): on tabs, it fits a 1080p screen - the
two columns of before had grown to 1183 px and the OK button was just
reachable (user 14.11.2026). Built with real Tk and EDMC's notebook
widgets stood in by ttk; every setting prefs_changed reads is on a tab.

Needs a display; without one (a headless CI runner) it says so and passes.

    python tests/prefs_layout.py      (from the plugin folder)
"""
import importlib
import os
import re
import sys
import tkinter as tk
import types
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plugin_pkg  # noqa: E402

MAX_H = 700               # px: room for EDMC's own tabs and buttons on a 1080p screen

try:
    root = tk.Tk()
except tk.TclError as e:
    print("prefs layout: no display here (%s) - skipped" % e)
    sys.exit(0)

nbm = types.ModuleType("myNotebook")      # EDMC's myNotebook is ttk underneath
nbm.Frame, nbm.Label, nbm.Checkbutton = ttk.Frame, ttk.Label, ttk.Checkbutton
nbm.EntryMenu, nbm.Notebook = ttk.Entry, ttk.Notebook
plugin_pkg.stub_edmc()
sys.modules["myNotebook"] = nbm
plugin_pkg.package()
importlib.import_module("SHBOXSEARCH.load")
from SHBOXSEARCH import planning, prefs, state  # noqa: E402
plugin_pkg.use_settings({})

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


class Sources:
    def status(self):
        return [("EDDiscovery", True, "C:/EDD/EDDSystem.sqlite"), ("Spansh", True, "online"),
                ("EDSM", True, "online")]


state.ST.sources = Sources()
state.ST.db = None
planning._main_cmdr_choices = lambda: [("Cmdr One", "F1"), ("Cmdr Two", "F2")]   # the longer Data tab
outer = ttk.Notebook(root)
outer.pack()
page = prefs.plugin_prefs(outer, "Cmdr One", False)
outer.add(page, text="SHBOXSEARCH")
root.update_idletasks()
tabs = [w for w in page.winfo_children() if isinstance(w, ttk.Notebook)]
names = [tabs[0].tab(t, "text") for t in tabs[0].tabs()] if tabs else []
check(names == ["Survey", "Data", "Overlay", "Windows", "FIS", "Maintenance"], "the tabs: %s" % names)
h, w = page.winfo_reqheight(), page.winfo_reqwidth()
check(h <= MAX_H, "the page is %d px tall (at most %d; it was 1183)" % (h, MAX_H))
check(w <= 900, "and %d px wide" % w)
src = open(os.path.join(os.path.dirname(HERE), "prefs.py"), encoding="utf-8").read()
read = set(re.findall(r'_p\["([a-z_]+)"\]', src[src.index("def prefs_changed"):]))
missing = sorted(read - set(prefs._p))
check(not missing, "every setting prefs_changed reads is on a tab (missing: %s)" % missing)
root.destroy()

print("prefs layout: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
