# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Package import test (4.11, S3): the plugin's modules load as members of
the plugin's package, never as top-level modules with generic names that
other plugins could shadow or be shadowed by (EDMC PLUGINS.md, "Common
resources"), and the plugin folder is not put on sys.path.

Both ways EDMC loads a plugin are checked, each in a fresh interpreter:
  1. the normal one: import_module(".load", "<folder>")
  2. the fallback for a folder name that is no Python name: the file by
     path, without a package - load.py registers a package of its own.

    python tests/package_import.py      (from the plugin folder)
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_MODULES = ["load", "state", "uithread", "panel", "planning", "cockpit", "routewin", "skin",
                  "survey", "updater", "fislaunch", "statswin", "journal", "probewin", "miningwin",
                  "prefs", "maintenance", "procgen", "sysdb", "sources", "netgate", "shells",
                  "deepspace", "sysroute", "boxelplan", "overlay", "biopredict", "surfacenav",
                  "miningstat", "journalscan", "regionmap", "edts_pgnames"]
HOOKS = ["plugin_start3", "plugin_stop", "plugin_app", "plugin_prefs", "prefs_changed",
         "journal_entry", "dashboard_entry", "capi_fleetcarrier"]

COMMON = r'''
import importlib, importlib.util, sys
sys.path.insert(0, HERE)
import plugin_pkg
plugin_pkg.stub_edmc()
sys.path.remove(HERE)
'''

NORMAL = COMMON + r'''
# EDMC: the plugins folder is on sys.path, the folder is the package.
import importlib.machinery
spec = importlib.machinery.ModuleSpec("SHBOXSEARCH", None, is_package=True)
spec.submodule_search_locations = [ROOT]
sys.modules["SHBOXSEARCH"] = importlib.util.module_from_spec(spec)
mod = importlib.import_module(".load", "SHBOXSEARCH")
pkg = "SHBOXSEARCH"
'''

FALLBACK = COMMON + r'''
# EDMC's fallback (plug.py): load the file by path under a safe name.
spec = importlib.util.spec_from_file_location("plugin_SHBOXSEARCH_main", ROOT + "/load.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[mod.__name__] = mod
spec.loader.exec_module(mod)
pkg = "shboxsearch_plugin"
'''

CHECK = r'''
missing = [h for h in HOOKS if not callable(getattr(mod, h, None))]
generic = sorted(m for m in PLUGIN_MODULES if m in sys.modules)
members = sorted(m for m in PLUGIN_MODULES if pkg + "." + m in sys.modules)
on_path = [p for p in sys.path if p and __import__("os").path.abspath(p) == ROOT]
print("missing hooks:", missing)
print("generic top-level modules:", generic)
print("package members:", len(members))
print("plugin folder on sys.path:", bool(on_path))
sys.exit(1 if missing or generic or on_path or len(members) < 25 else 0)
'''

fails = 0


def run(name, script):
    global fails
    code = "ROOT = %r\nHERE = %r\nPLUGIN_MODULES = %r\nHOOKS = %r\n" % (ROOT, HERE, PLUGIN_MODULES, HOOKS)
    r = subprocess.run([sys.executable, "-c", code + script + CHECK], capture_output=True, text=True,
                       cwd=os.path.dirname(ROOT))
    ok = r.returncode == 0
    fails += 0 if ok else 1
    print("  [%s] %s" % ("OK" if ok else "FAIL", name))
    for ln in (r.stdout + r.stderr).strip().splitlines()[-8:]:
        print("        " + ln)


run("EDMC's normal import: <folder>.load as a package", NORMAL)
run("EDMC's fallback: load.py by path registers its own package", FALLBACK)

# the plugin and the FIS are released together: one version number
with open(os.path.join(ROOT, "state.py"), encoding="utf-8") as fh:
    plugin_v = re.search(r'^VERSION = "([^"]+)"', fh.read(), re.M).group(1)
with open(os.path.join(ROOT, "FIS", "fis", "__init__.py"), encoding="utf-8") as fh:
    fis_v = re.search(r'^__version__ = "([^"]+)"', fh.read(), re.M).group(1)
same = plugin_v == fis_v and re.fullmatch(r"\d+\.\d+\.\d+", plugin_v) is not None
fails += 0 if same else 1
print("  [%s] plugin %s and FIS %s: the same SemVer version" % ("OK" if same else "FAIL", plugin_v, fis_v))
print("package import: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
