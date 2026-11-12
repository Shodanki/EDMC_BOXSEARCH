# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SHIP -> LOST DATA: which crash losses the commander no longer wants listed.

The plugin marks data that went down with the ship (cmdr_bodies.lost_what /
lost_ts); the FIS opens that database read-only. Hiding an entry here only
takes it off the LIST - the tasks stay reset, so route and SYSTEM still plan
them.

FIS/lost_hidden.json (personal - never in the repository), per commander FID:

  hidden   [{id64, what, ts, at}]   what None = the whole system, or "scan",
           "map", "bio:<species>"; ts = the system's lost_ts the hide belongs
           to - a later crash (newer lost_ts) lists the system again

Written atomically (temporary file + os.replace), like favourites.json; a
broken file is read as empty and kept aside as .bad.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_ENTRIES = 5000
MAX_SPECIES = 80
CAPS_LY = (100, 250, 500, 1000)
_FID = re.compile(r"^[A-Za-z0-9_]{1,24}$")


def _fid(fid: Optional[str]) -> str:
    return fid if fid and _FID.match(fid) else "_"


def valid_what(what: Any) -> bool:
    """None (whole system), 'scan', 'map' or 'bio:<species>'."""
    if what is None or what in ("scan", "map"):
        return True
    return (isinstance(what, str) and what.startswith("bio:") and 0 < len(what) - 4 <= MAX_SPECIES
            and "\n" not in what and "\r" not in what)


def distance(pos: Optional[Sequence[float]], s: Dict[str, Any]) -> Optional[float]:
    """Light years from `pos` to the system of a lost entry (None if unknown)."""
    p = s.get("pos")
    if not pos or not p or None in p:
        return None
    try:
        return round(math.dist([float(v) for v in pos[:3]], [float(v) for v in p[:3]]), 1)
    except (TypeError, ValueError):
        return None


def apply(lost: Iterable[Dict[str, Any]], hidden: Iterable[Dict[str, Any]],
          pos: Optional[Sequence[float]] = None) -> Tuple[List[Dict[str, Any]], int]:
    """The lost systems without the hidden entries, each with `dist` (ly from
    pos), sorted by date (newest day first) then distance. Returns
    (visible, number of hidden entries that still apply)."""
    by: Dict[int, List[Dict[str, Any]]] = {}
    for h in hidden:
        by.setdefault(h.get("id64"), []).append(h)
    out: List[Dict[str, Any]] = []
    n_hidden = 0
    for s in lost:
        hs = [h for h in by.get(s.get("id64"), []) if (h.get("ts") or "") >= (s.get("ts") or "")]
        d = dict(s, bio=list(s.get("bio") or []))
        whole = False
        for h in hs:
            w = h.get("what")
            if w is None:
                whole = True
            elif w in ("scan", "map") and d.get(w):
                d[w] = 0
            elif isinstance(w, str) and w.startswith("bio:") and w[4:] in d["bio"]:
                d["bio"] = [b for b in d["bio"] if b != w[4:]]
            else:
                continue
            n_hidden += 1
        if whole or not (d.get("scan") or d.get("map") or d["bio"]):
            continue
        d["dist"] = distance(pos, d)
        out.append(d)
    out.sort(key=lambda d: (d["dist"] is None, d["dist"] or 0.0))
    out.sort(key=lambda d: str(d.get("ts") or "")[:10], reverse=True)
    return out, n_hidden


def beyond(visible: Iterable[Dict[str, Any]], ly: float) -> List[Dict[str, Any]]:
    """The listed systems farther than `ly` from here (unknown distance stays)."""
    return [s for s in visible if s.get("dist") is not None and s["dist"] > ly]


class LostHiddenStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: Optional[Dict[str, Any]] = None
        self._mtime: Optional[float] = None

    # ------------------------------------------------------------ file
    def _load(self) -> Dict[str, Any]:
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            mt = None
        if self._data is not None and mt == self._mtime:
            return self._data
        data: Dict[str, Any] = {"version": 1, "commanders": {}}
        if mt is not None:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    got = json.load(fh)
                if isinstance(got, dict) and isinstance(got.get("commanders"), dict):
                    data = got
                else:
                    raise ValueError("unexpected layout")
            except (OSError, ValueError):
                try:
                    os.replace(self.path, self.path + ".bad")
                except OSError:
                    pass
        self._data, self._mtime = data, mt
        return data

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        try:
            self._mtime = os.path.getmtime(self.path)
        except OSError:
            self._mtime = None

    def _list(self, fid: Optional[str]) -> List[Dict[str, Any]]:
        c = self._load()["commanders"].setdefault(_fid(fid), {})
        if not isinstance(c.get("hidden"), list):
            c["hidden"] = []
        return c["hidden"]

    # ------------------------------------------------------------ read
    def get(self, fid: Optional[str]) -> List[Dict[str, Any]]:
        """The hidden entries of one commander (a copy)."""
        with self._lock:
            return [dict(h) for h in self._list(fid) if isinstance(h, dict)]

    # ------------------------------------------------------------ write
    def hide(self, fid: Optional[str], items: Iterable[Tuple[int, Optional[str]]],
             lost: Iterable[Dict[str, Any]]) -> int:
        """Hide (id64, what) pairs, each tied to the system's current lost_ts
        from `lost` (the database's lost list). Pairs of systems not lost are
        ignored; entries of systems no longer lost or lost again are pruned.
        Returns the number of new entries."""
        lost_ts = {s.get("id64"): s.get("ts") or "" for s in lost}
        with self._lock:
            lst = self._list(fid)
            keep = [h for h in lst if isinstance(h, dict) and h.get("id64") in lost_ts
                    and (h.get("ts") or "") >= lost_ts[h["id64"]]]
            have = {(h["id64"], h.get("what")) for h in keep}
            added = 0
            now = time.time()
            for id64, what in items:
                if id64 not in lost_ts or not valid_what(what) or (id64, what) in have:
                    continue
                if len(keep) >= MAX_ENTRIES:
                    raise ValueError("too many hidden entries")
                keep.append({"id64": id64, "what": what, "ts": lost_ts[id64], "at": round(now)})
                have.add((id64, what))
                added += 1
            lst[:] = keep
            self._save()
            return added

    def reset(self, fid: Optional[str]) -> int:
        """Show everything again. Returns how many entries were removed."""
        with self._lock:
            lst = self._list(fid)
            n = len(lst)
            lst[:] = []
            self._save()
            return n
