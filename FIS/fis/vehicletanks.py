# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
V1b: the tank size of each surface vehicle type, learnt from the game.

No game file names a vehicle's tank size. Status.json shows its fill
(FuelReservoir while in the vehicle), and a refuel synthesis ("Fuel Basic",
"Fuel Standard" ...) fills it at once - recorded 12.11.2026 in the Scarab:
0.488 -> 0.500 t two seconds after "Fuel Basic". The first Status.json
reading after such a synthesis is therefore the full tank.

FIS/vehicle_tanks.json (written by the FIS, never in the repository), per
vehicle type as the Launch event names it (testbuggy, mev_rhino ...):

  {"version": 1, "types": {"testbuggy": {"t": 0.5, "name": "SRV Scarab",
                                         "ts": "2026-11-12T17:40:59Z"}}}

Written atomically (temporary file + os.replace); a broken file is read as
empty and kept aside as .bad.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, Optional

_TYPE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
MAX_T = 10.0                 # a vehicle tank, not a ship's: anything above is a misreading


class VehicleTankStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: Optional[Dict[str, Any]] = None
        self._mtime: Optional[float] = None

    def _load(self) -> Dict[str, Any]:
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            mt = None
        if self._data is not None and mt == self._mtime:
            return self._data
        data: Dict[str, Any] = {"version": 1, "types": {}}
        if mt is not None:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    got = json.load(fh)
                if isinstance(got, dict) and isinstance(got.get("types"), dict):
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

    def all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._load()["types"].items() if isinstance(v, dict)}

    def get(self, typ: Optional[str]) -> Optional[Dict[str, Any]]:
        return self.all().get(typ or "")

    def learn(self, typ: Optional[str], tonnes: Any, name: Optional[str] = None,
              ts: Optional[str] = None) -> bool:
        """Store a full-tank reading; True when it changed the file."""
        if not typ or not _TYPE.match(typ):
            return False
        try:
            t = round(float(tonnes), 3)
        except (TypeError, ValueError):
            return False
        if not 0 < t <= MAX_T:
            return False
        with self._lock:
            types = self._load()["types"]
            old = types.get(typ) if isinstance(types.get(typ), dict) else None
            if old is not None and old.get("t") == t:
                return False
            types[typ] = {"t": t, "name": (name or "")[:60] or None, "ts": ts}
            self._save()
            return True
