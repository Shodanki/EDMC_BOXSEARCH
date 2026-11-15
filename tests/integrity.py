# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
File check (4.12, integrity.py): on a copy of the download - all files as
released, line endings changed (still fine), a file missing, a file
changed, the manifest missing; the plugin loaded the way EDMC loads it with
a module missing (a red line and the log instead of a traceback); the full
check at a normal start (log and panel).

    python tests/integrity.py      (from the plugin folder)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH import integrity  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


def copy_download(dest: str) -> None:
    """The files the manifest lists, and the manifest - as the ZIP holds them."""
    version, files = integrity.load_manifest(ROOT)
    for rel in files:
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, *rel.split("/")), target)
    shutil.copyfile(os.path.join(ROOT, integrity.MANIFEST), os.path.join(dest, integrity.MANIFEST))


work = tempfile.mkdtemp()
plug = os.path.join(work, "plugins", "SHBOXSEARCH")
copy_download(plug)

print("the check on a copy of the download")
res = integrity.check(plug)
check(res["ok"] and res["files"] > 100 and not integrity.summary(res),
      "all %d files as released, nothing to say" % res["files"])
with open(os.path.join(plug, "sysroute.py"), "rb") as fh:
    data = fh.read()
with open(os.path.join(plug, "sysroute.py"), "wb") as fh:
    fh.write(data.replace(b"\n", b"\r\n"))
check(integrity.check(plug)["ok"], "line endings changed to CRLF: still as released")
with open(os.path.join(plug, "sysroute.py"), "ab") as fh:
    fh.write(b"# touched\r\n")
os.remove(os.path.join(plug, "FIS", "web", "js", "app.js"))
res = integrity.check(plug)
check(res["missing"] == ["FIS/web/js/app.js"] and res["changed"] == ["sysroute.py"] and not res["ok"],
      "one missing, one changed: %s / %s" % (res["missing"], res["changed"]))
s = integrity.summary(res)
check("1 missing" in s and "1 changed or damaged" in s and "release ZIP" in s, "summary names both and the remedy")
check(integrity.details(res) == ["missing: FIS/web/js/app.js", "changed or damaged: sysroute.py"],
      "details: one line per file")
check(integrity.missing(plug) == ["FIS/web/js/app.js"], "missing() without hashing")
check(integrity.check(plug, only="FIS/")["changed"] == [], "only one folder when asked")
shutil.copyfile(os.path.join(ROOT, "sysroute.py"), os.path.join(plug, "sysroute.py"))
shutil.copyfile(os.path.join(ROOT, "FIS", "web", "js", "app.js"), os.path.join(plug, "FIS", "web", "js", "app.js"))
os.rename(os.path.join(plug, integrity.MANIFEST), os.path.join(plug, "m.bak"))
res = integrity.check(plug)
check(not res["ok"] and not res["manifest"] and integrity.MANIFEST in integrity.summary(res),
      "manifest missing: said so, not a silent pass")
os.rename(os.path.join(plug, "m.bak"), os.path.join(plug, integrity.MANIFEST))

print("EDMC loads the plugin with a module missing")
os.remove(os.path.join(plug, "routewin.py"))
script = r'''
import importlib, logging, os, sys
sys.path.insert(0, HERE)
import plugin_pkg
plugin_pkg.stub_edmc()
sys.path.remove(HERE)
lines = []
class H(logging.Handler):
    def emit(self, r):
        lines.append(r.getMessage())
logging.getLogger().addHandler(H())
logging.getLogger().setLevel(logging.INFO)
sys.path.append(PLUGINS)
mod = importlib.import_module(".load", "SHBOXSEARCH")
print("NAME", mod.plugin_start3(os.path.join(PLUGINS, "SHBOXSEARCH")))
print("HOOKS", sorted(h for h in ("journal_entry", "dashboard_entry", "plugin_prefs", "prefs_changed",
                                  "capi_fleetcarrier") if hasattr(mod, h)))
mod.plugin_stop()
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    print("LABEL", mod.plugin_app(root).cget("text"))
    root.destroy()
except Exception as e:
    print("LABEL skipped", type(e).__name__)
for ln in lines:
    print("LOG", ln)
'''
r = subprocess.run([sys.executable, "-c", "HERE = %r\nPLUGINS = %r\n" % (HERE, os.path.dirname(plug)) + script],
                   capture_output=True, text=True, cwd=work)
out = r.stdout
check(r.returncode == 0 and "NAME SHBOXSEARCH" in out, "the plugin loads and names itself (no traceback)")
check("HOOKS []" in out, "no hooks that would need the missing modules")
check("LOG   missing: routewin.py" in out and "release ZIP" in out,
      "the log names the file and the remedy")
check("1 file(s) missing or damaged" in out or "LABEL skipped" in out,
      "a red line in EDMC's window names it")
if r.returncode:
    print(r.stderr[-800:])
shutil.copyfile(os.path.join(ROOT, "routewin.py"), os.path.join(plug, "routewin.py"))

print("a normal start: the full check in the background")
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import maintenance, state, panel  # noqa: E402
calls = []
maintenance.uithread._ui = lambda fn: calls.append(fn)
maintenance._PLUGIN_DIR = plug
state.ST.files_problem = ""
maintenance._check_files()
check(state.ST.files_problem == "" and not calls, "all files as released: nothing shown")
with open(os.path.join(plug, "netgate.py"), "ab") as fh:
    fh.write(b"# changed\n")
maintenance._check_files()
check("1 changed or damaged" in state.ST.files_problem and calls == [panel._refresh],
      "a changed file: the panel line is set and redrawn (%s)" % state.ST.files_problem[:60])

shutil.rmtree(work, ignore_errors=True)
print("integrity: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
