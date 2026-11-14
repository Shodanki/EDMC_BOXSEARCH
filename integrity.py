# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12: are all files of this version there and unchanged?

The release carries ``SHBOXSEARCH.manifest``: the SHA-256 of every file
the plugin and the FIS run from (made by ``tests/manifest.py --write``,
checked by CI). The plugin checks it at every EDMC start, the FIS at every
start of its own; what is missing or not as released is named, with the
remedy: copy the plugin from the release ZIP again.

* ``missing()``  only whether the files exist - milliseconds, so the plugin
  can ask it before it imports its own modules;
* ``check()``    the full check, every file hashed (a few dozen ms).

Line endings do not count (a text file with CRLF hashes like the same file
with LF): an editor or a Git setting that changes them breaks nothing.
Files the plugin writes itself (database, settings, favourites ...) are
not in the manifest and never checked.

Standard library only; nothing is written, nothing is sent.
"""

from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional, Tuple

MANIFEST = "SHBOXSEARCH.manifest"
HEADER = "# SHBOXSEARCH %s - SHA-256 of every file of this version (line endings as LF)"
TEXT_EXT = frozenset((".py", ".js", ".css", ".html", ".md", ".txt", ".json", ".bat", ".svg", ".ini",
                      ".example", ".webmanifest", ".toml", ".csv", ".cfg", ".gitattributes"))
REMEDY = ("copy the plugin folder from the release ZIP again (your database and settings "
          "are separate files and stay)")


def file_hash(path: str) -> str:
    """SHA-256 of a file as the manifest counts it: text with LF line endings."""
    with open(path, "rb") as fh:
        data = fh.read()
    if os.path.splitext(path)[1].lower() in TEXT_EXT or os.path.basename(path) == "LICENSE":
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_manifest(root: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """(version, {relative path: sha256}) from the manifest, None when it is
    missing or unreadable."""
    try:
        with open(os.path.join(root, MANIFEST), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    version = ""
    files: Dict[str, str] = {}
    for ln in lines:
        if ln.startswith("# SHBOXSEARCH "):
            version = ln.split()[2]
        elif ln and not ln.startswith("#"):
            digest, _, rel = ln.partition("  ")
            if len(digest) == 64 and rel:
                files[rel] = digest
    return (version, files) if files else None


def missing(root: str, manifest: Optional[Tuple[str, Dict[str, str]]] = None) -> List[str]:
    """The files of the manifest that are not there (no hashing)."""
    m = manifest or load_manifest(root)
    if m is None:
        return []
    return sorted(rel for rel in m[1] if not os.path.isfile(os.path.join(root, *rel.split("/"))))


def check(root: str, only: Optional[str] = None) -> Dict[str, object]:
    """The full check: {"ok", "version", "manifest", "missing", "changed",
    "files"}. ``only`` limits it to the paths below one folder ("FIS/")."""
    m = load_manifest(root)
    out: Dict[str, object] = {"ok": False, "version": None, "manifest": m is not None,
                              "missing": [], "changed": [], "files": 0}
    if m is None:
        return out
    version, files = m
    out["version"] = version
    gone, changed = [], []
    for rel, digest in sorted(files.items()):
        if only and not rel.startswith(only):
            continue
        out["files"] = int(out["files"]) + 1        # type: ignore[call-overload]
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(path):
            gone.append(rel)
            continue
        try:
            if file_hash(path) != digest:
                changed.append(rel)
        except OSError:
            changed.append(rel)
    out.update(ok=not gone and not changed, missing=gone, changed=changed)
    return out


def summary(res: Dict[str, object]) -> str:
    """One line: what is wrong, and the remedy ("" when all is well)."""
    if res.get("ok"):
        return ""
    if not res.get("manifest"):
        return "file check: %s is missing - %s" % (MANIFEST, REMEDY)
    gone, changed = list(res.get("missing") or []), list(res.get("changed") or [])
    bits = []
    if gone:
        bits.append("%d missing" % len(gone))
    if changed:
        bits.append("%d changed or damaged" % len(changed))
    return "files of %s: %s - %s" % (res.get("version") or "?", ", ".join(bits), REMEDY)


def details(res: Dict[str, object]) -> List[str]:
    """One line per file that is missing or not as released."""
    return (["missing: " + f for f in res.get("missing") or []]          # type: ignore[union-attr]
            + ["changed or damaged: " + f for f in res.get("changed") or []])  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# the plugin when its own files are broken: one line in EDMC's window
# ---------------------------------------------------------------------------

class BrokenPlugin:
    """What EDMC gets when the plugin's modules could not be loaded: a name,
    a red line in the main window and the details in EDMC's log - instead of
    a traceback the user cannot act on."""

    def __init__(self, root: str, error: BaseException) -> None:
        self.root, self.error = root, error
        self.res = check(root)
        import logging
        try:
            from config import appname           # EDMC's logger tree
            self.log = logging.getLogger("%s.%s" % (appname, os.path.basename(root)))
        except Exception:
            self.log = logging.getLogger("SHBOXSEARCH")

    def plugin_start3(self, plugin_dir: str) -> str:
        """EDMC hook: name the plugin and log what is wrong."""
        self.log.error("SHBOXSEARCH could not load: %s: %s", type(self.error).__name__, self.error,
                       exc_info=self.error)
        self.log.error("%s", summary(self.res) or "file check: all files as released - " + REMEDY)
        for line in details(self.res):
            self.log.error("  %s", line)
        return "SHBOXSEARCH"

    def plugin_app(self, parent: object) -> object:
        """EDMC hook: one line in the main window."""
        import tkinter as tk
        res = self.res
        n = len(res.get("missing") or []) + len(res.get("changed") or [])   # type: ignore[arg-type]
        text = ("SHBOXSEARCH: %d file(s) missing or damaged - copy the plugin from the release ZIP "
                "again (details in the EDMC log)" % n if n else
                "SHBOXSEARCH could not start - copy the plugin from the release ZIP again "
                "(details in the EDMC log)")
        return tk.Label(parent, text=text, fg="red", anchor="w", justify="left", wraplength=360)

    def plugin_stop(self) -> None:
        """EDMC hook: nothing to stop."""
        return None
