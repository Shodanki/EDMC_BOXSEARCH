# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
K2/K3: carrier favourites and the last market seen at other carriers.

FIS/favourites.json (personal - never in the repository), per commander
(FID), because one journal folder can hold several commanders:

  favourites  callsign -> when added, a note, and the last known position at
              the time (so a favourite survives even when old journals are
              deleted - the journal archive is the newer source while it has
              the carrier)
  markets     callsign -> the last Market.json snapshot of that carrier
              (what it bought and sold, with the time) - kept for every
              visited carrier, the newest MAX_MARKETS

Written atomically (temporary file + os.replace), so a crash never leaves a
half file; a broken file is read as empty and kept aside as .bad.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, Optional

from .carriers import is_callsign

MAX_FAVOURITES = 200
MAX_NOTE = 200
MAX_MARKETS = 60
MAX_ITEMS = 40            # per list in a market snapshot
_FID = re.compile(r"^[A-Za-z0-9_]{1,24}$")
_POS_KEYS = ("name", "market_id", "system", "id64", "pos", "ts", "how")


def _fid(fid: Optional[str]) -> str:
    return fid if fid and _FID.match(fid) else "_"


class FavouriteStore:
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

    def _cmdr(self, fid: Optional[str]) -> Dict[str, Any]:
        c = self._load()["commanders"].setdefault(_fid(fid), {})
        c.setdefault("favourites", {})
        c.setdefault("markets", {})
        return c

    # ------------------------------------------------------------ read
    def get(self, fid: Optional[str]) -> Dict[str, Any]:
        """{'favourites': {...}, 'markets': {...}} of one commander (a copy)."""
        with self._lock:
            c = self._cmdr(fid)
            return json.loads(json.dumps({"favourites": c["favourites"], "markets": c["markets"]}))

    # ------------------------------------------------------------ write
    def set_favourite(self, fid: Optional[str], callsign: str, on: bool,
                      note: Optional[str] = None,
                      info: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Star / unstar a carrier. Returns the favourite (None when removed).
        Raises ValueError for a bad callsign or a full list."""
        if not is_callsign(callsign):
            raise ValueError("bad callsign")
        with self._lock:
            favs = self._cmdr(fid)["favourites"]
            if not on:
                favs.pop(callsign, None)
                self._save()
                return None
            f = favs.get(callsign)
            if f is None:
                if len(favs) >= MAX_FAVOURITES:
                    raise ValueError("too many favourites")
                f = favs[callsign] = {"added": time.time(), "note": ""}
            if note is not None:
                f["note"] = str(note).replace("\r", " ").replace("\n", " ").strip()[:MAX_NOTE]
            for k in _POS_KEYS:
                if info and info.get(k) is not None:
                    f[k] = info[k]
            self._save()
            return dict(f)

    def remember_position(self, fid: Optional[str], callsign: str, info: Dict[str, Any]) -> bool:
        """Keep a favourite's stored position current (only when newer)."""
        with self._lock:
            f = self._cmdr(fid)["favourites"].get(callsign)
            if not f or not info.get("ts") or (f.get("ts") or "") >= info["ts"]:
                return False
            for k in _POS_KEYS:
                if info.get(k) is not None:
                    f[k] = info[k]
            self._save()
            return True

    def set_online(self, fid: Optional[str], callsign: str, info: Dict[str, Any]) -> bool:
        """K5: keep the answer of an online lookup with the favourite."""
        keep = {k: info.get(k) for k in ("checked", "found", "source", "system", "id64",
                                         "market_id", "updated", "pos", "docking_access")}
        with self._lock:
            f = self._cmdr(fid)["favourites"].get(callsign)
            if not f:
                return False
            f["online"] = keep
            self._save()
            return True

    def note_market(self, fid: Optional[str], vis: Dict[str, Any]) -> bool:
        """K3: keep the market of a visited carrier (from visiting_carrier).
        Only a newer snapshot replaces the stored one."""
        cs = vis.get("callsign")
        ts = vis.get("market_ts") or ""
        if not is_callsign(cs) or not ts:
            return False
        snap = {"ts": ts, "system": vis.get("system"), "access": vis.get("access"),
                "buys": [{k: b.get(k) for k in ("key", "name", "price", "demand")}
                         for b in (vis.get("buys") or [])[:MAX_ITEMS]],
                "sells": [{k: s.get(k) for k in ("key", "name", "price", "stock")}
                          for s in (vis.get("sells") or [])[:MAX_ITEMS]]}
        with self._lock:
            mk = self._cmdr(fid)["markets"]
            old = mk.get(cs)
            if old and (old.get("ts") or "") >= ts:
                return False
            mk[cs] = snap
            if len(mk) > MAX_MARKETS:
                for k in sorted(mk, key=lambda k: mk[k].get("ts") or "")[:len(mk) - MAX_MARKETS]:
                    del mk[k]
            self._save()
            return True
