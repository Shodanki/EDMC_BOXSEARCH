# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12: the file check at every FIS start - the plugin's integrity.py and its
manifest, read from the plugin folder this FIS lives in. The FIS runs from
the plugin's modules too, so the whole download is checked.

What is missing or not as released is printed in the console (English and
German) before the server starts, and given to the browser (``/api/config``
-> ``files``) for a banner. Relative file names only - no paths of this PC.
When a file the FIS itself needs is gone, it says so instead of a traceback.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Callable, Dict, Optional

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOWN = 20                       # file names given to the browser at most
REMEDY_DE = ("den Plugin-Ordner noch einmal aus dem Release-ZIP kopieren (Datenbank und "
             "Einstellungen sind eigene Dateien und bleiben)")

RESULT: Dict[str, Any] = {"ok": True, "checked": False}


def _integrity(root: str = PLUGIN_ROOT) -> Optional[Any]:
    """The plugin's integrity.py, loaded by path; None when it is not there."""
    path = os.path.join(root, "integrity.py")
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location("shbox_integrity", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)            # type: ignore[union-attr]
        return mod
    except Exception:                           # broken itself: count as missing
        return None


def check(root: str = PLUGIN_ROOT) -> Dict[str, Any]:
    """The full check (integrity.check), or a result naming integrity.py
    as missing when the check itself is gone."""
    mod = _integrity(root)
    if mod is None:
        return {"ok": False, "checked": True, "manifest": False, "version": None,
                "missing": ["integrity.py"], "changed": [], "files": 0}
    res = dict(mod.check(root))
    res["checked"] = True
    return res


def german(res: Dict[str, Any]) -> str:
    """The summary line in German ("" when all is well)."""
    if res.get("ok"):
        return ""
    if not res.get("manifest"):
        return "Dateiprüfung: SHBOXSEARCH.manifest oder integrity.py fehlt - " + REMEDY_DE
    bits = []
    if res.get("missing"):
        bits.append("fehlend: %d" % len(res["missing"]))
    if res.get("changed"):
        bits.append("verändert oder beschädigt: %d" % len(res["changed"]))
    return "Dateien von %s: %s - %s" % (res.get("version") or "?", ", ".join(bits), REMEDY_DE)


def english(res: Dict[str, Any]) -> str:
    """The summary line in English ("" when all is well)."""
    if res.get("ok"):
        return ""
    mod = _integrity()
    if mod is not None:
        return mod.summary(res)
    return "file check: integrity.py is missing - copy the plugin folder from the release ZIP again"


def startup_check(out: Callable[[str], None] = print, root: str = PLUGIN_ROOT) -> Dict[str, Any]:
    """Run the check once, keep it for the browser, print what is wrong."""
    res = check(root)
    RESULT.clear()
    RESULT.update(res)
    if not res.get("ok"):
        out("")
        out("!! " + english(res))
        out("!! " + german(res))
        for f in res.get("missing") or []:
            out("   missing / fehlt: " + f)
        for f in res.get("changed") or []:
            out("   changed or damaged / verändert oder beschädigt: " + f)
        out("")
    return res


def cannot_start(exc: BaseException, out: Callable[[str], None] = print) -> None:
    """The FIS could not load its own modules: why, and the remedy."""
    out("SHBOX FIS cannot start: %s: %s" % (type(exc).__name__, exc))
    if RESULT.get("checked") and not RESULT.get("ok"):
        return                                   # the file list is printed already
    out("Copy the plugin folder from the release ZIP again.")
    out("Den Plugin-Ordner noch einmal aus dem Release-ZIP kopieren.")


def for_browser() -> Dict[str, Any]:
    """What the page shows: ok, version, and the first file names."""
    res = RESULT
    return {"ok": bool(res.get("ok", True)), "checked": bool(res.get("checked")),
            "manifest": res.get("manifest", True), "version": res.get("version"),
            "missing": list(res.get("missing") or [])[:SHOWN],
            "changed": list(res.get("changed") or [])[:SHOWN],
            "n_missing": len(res.get("missing") or []), "n_changed": len(res.get("changed") or [])}
