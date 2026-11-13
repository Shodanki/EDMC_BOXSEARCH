# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
K5: where is a favourite carrier now? - one lookup at Spansh, on a click.

The only thing in the FIS that asks a service on the internet, and only
when the commander clicks it for one favourite:

* through the plugin's netgate.Gateway (pacing, Retry-After, back-off,
  honest User-Agent, daily cap 50 per service) - with a small urllib
  session, because the FIS needs nothing beyond the standard library;
  today's count starts from the plugin's own call log (read only), so the
  cap is shared
* never while the plugin's "offline" switch is on
* at most once per carrier every CACHE_S (the answer is kept with the
  favourite, the button says when it was asked)
* Spansh POST /api/stations/search, name = callsign, type Drake-Class
  Carrier. Its name filter is a token match (asking for "G6M-8QZ" also
  lists "TLY-G6M"), so only the exact callsign counts.

Spansh knows where someone last docked and reported it through EDDN - the
answer can be hours or weeks old, and is always shown with its date.

H2 (4.12): carriers near you - the same rules, one request on a click:
Spansh stations/search for Drake-Class Carriers within NEARBY_LY of your
position, nearest first, NEARBY_SIZE of them. The answer is kept for
NEARBY_CACHE_S per CELL_LY cell of space (asking again in the same region
asks nothing); distances are worked out again from where you are.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SPANSH_STATIONS = "https://spansh.co.uk/api/stations/search"
CACHE_S = 6 * 3600.0
CARRIER_TYPES = ["Drake-Class Carrier"]
NEARBY_LY = 100           # H2: how far to look
NEARBY_SIZE = 15          # how many carriers, nearest first
NEARBY_CACHE_S = 24 * 3600.0
CELL_LY = 50.0            # one answer per cell of space and day
# Spansh service names -> the FIS's keys (what an explorer far out needs)
NEARBY_SERVICES = {"Refuel": "refuel", "Repair": "repair", "Restock": "rearm",
                   "Universal Cartographics": "exploration", "Vista Genomics": "vistagenomics",
                   "Shipyard": "shipyard", "Outfitting": "outfitting", "Market": "commodities"}


class _Resp:
    def __init__(self, status: int, headers: Any, body: bytes) -> None:
        self.status_code = status
        self.headers = headers if headers is not None else {}
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self._body.decode("utf-8"))


class UrllibSession:
    """What netgate.Gateway needs from a requests.Session, on urllib."""

    def __init__(self) -> None:
        self.headers: Dict[str, str] = {}

    def request(self, method: str, url: str, json_body: Any = None, timeout: float = 20.0,
                **kw: Any) -> _Resp:
        if json_body is None:
            json_body = kw.get("json")
        data = None
        headers = dict(self.headers)
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=kw.get("timeout", timeout)) as r:
                return _Resp(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return _Resp(e.code, e.headers, e.read() if hasattr(e, "read") else b"")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _age_s(iso: Optional[str], now: float) -> Optional[float]:
    if not iso:
        return None
    try:
        import calendar
        return now - calendar.timegm(time.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


class CarrierLookup:
    """One Spansh lookup per click, through the plugin's gateway."""

    def __init__(self, version: str, calls_today: Callable[[], Dict[str, int]],
                 offline: Callable[[], bool], session_factory: Any = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._version = version
        self._calls_today = calls_today
        self._offline = offline
        self._factory = session_factory or UrllibSession
        self._clock = clock
        self._gw = None
        self._nearby: Dict[Tuple[int, int, int], Tuple[float, Dict[str, Any]]] = {}

    def _gateway(self) -> Any:
        if self._gw is None:
            import netgate  # type: ignore   # the plugin's module (plugin path)
            self._gw = netgate.Gateway(self._version, session_factory=self._factory,
                                       clock=self._clock)
        try:
            self._gw.seed_today(self._calls_today() or {})
        except Exception:
            pass
        return self._gw

    def cached(self, fav: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """The stored answer while it is younger than CACHE_S."""
        on = (fav or {}).get("online")
        age = _age_s((on or {}).get("checked"), self._clock())
        return on if on and age is not None and age < CACHE_S else None

    def lookup(self, callsign: str) -> Dict[str, Any]:
        """{'checked', 'found', 'system', 'id64', 'pos', 'updated', 'source'}
        or {'error': ...} when nothing could be asked."""
        if self._offline():
            return {"error": "offline"}
        gw = self._gateway()
        body = {"filters": {"name": {"value": callsign}, "type": {"value": CARRIER_TYPES}},
                "size": 10, "page": 0}
        resp = gw.request("spansh", "POST", SPANSH_STATIONS, "stations/search", json=body,
                          timeout=20)
        if resp is None:
            why = gw.resting("spansh") if hasattr(gw, "resting") else None
            return {"error": why or "Spansh did not answer"}
        if resp.status_code != 200:
            return {"error": "Spansh HTTP %d" % resp.status_code}
        try:
            res = resp.json().get("results") or []
        except ValueError:
            return {"error": "Spansh answer unreadable"}
        out: Dict[str, Any] = {"checked": _now_iso(), "found": False, "source": "Spansh"}
        hit = next((r for r in res if str(r.get("name") or "").upper() == callsign.upper()), None)
        if hit:
            pos = [hit.get("system_x"), hit.get("system_y"), hit.get("system_z")]
            out.update(found=True, system=hit.get("system_name"), id64=hit.get("system_id64"),
                       market_id=hit.get("market_id"), updated=hit.get("updated_at"),
                       # A1: who may dock - part of the same answer, no extra request
                       docking_access=hit.get("carrier_docking_access") or None,
                       pos=pos if all(v is not None for v in pos) else None)
        return out

    # ------------------------------------------------------------------ H2
    @staticmethod
    def _cell(pos: Sequence[float]) -> Tuple[int, int, int]:
        return tuple(int(math.floor(float(c) / CELL_LY)) for c in pos)   # type: ignore[return-value]

    def nearby(self, pos: Sequence[float]) -> Dict[str, Any]:
        """H2: the Drake-Class Carriers Spansh knows near ``pos`` -
        {'checked', 'ref', 'cached', 'carriers': [...]} nearest first, or
        {'error': ...}. One request per CELL_LY cell and NEARBY_CACHE_S."""
        cell = self._cell(pos)
        hit = self._nearby.get(cell)
        if hit and self._clock() - hit[0] < NEARBY_CACHE_S:
            return dict(hit[1], cached=True, carriers=_with_distance(hit[1]["carriers"], pos))
        if self._offline():
            return {"error": "offline"}
        gw = self._gateway()
        body = {"filters": {"type": {"value": CARRIER_TYPES},
                            "distance": {"min": "0", "max": str(NEARBY_LY)}},
                "sort": [{"distance": {"direction": "asc"}}], "size": NEARBY_SIZE, "page": 0,
                "reference_coords": {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2])}}
        resp = gw.request("spansh", "POST", SPANSH_STATIONS, "stations/search", json=body,
                          timeout=20)
        if resp is None:
            why = gw.resting("spansh") if hasattr(gw, "resting") else None
            return {"error": why or "Spansh did not answer"}
        if resp.status_code != 200:
            return {"error": "Spansh HTTP %d" % resp.status_code}
        try:
            rows = resp.json().get("results") or []
        except ValueError:
            return {"error": "Spansh answer unreadable"}
        out = {"checked": _now_iso(), "ref": [float(c) for c in pos],
               "carriers": [c for c in (_nearby_row(r) for r in rows) if c]}
        self._nearby[cell] = (self._clock(), out)
        return dict(out, cached=False, carriers=_with_distance(out["carriers"], pos))

    def from_nearby(self, callsign: str) -> Optional[Dict[str, Any]]:
        """A carrier of a fresh nearby answer, shaped like lookup()'s answer -
        a carrier starred from that list keeps where Spansh saw it, without
        asking again."""
        for at, ans in self._nearby.values():
            if self._clock() - at >= NEARBY_CACHE_S:
                continue
            for c in ans["carriers"]:
                if c["callsign"] == callsign:
                    return {"checked": ans["checked"], "found": True, "source": "Spansh",
                            "system": c["system"], "id64": c["id64"], "pos": c["pos"],
                            "updated": c["updated"], "docking_access": c["access"]}
        return None


def _nearby_row(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One carrier of a Spansh answer, as the CARRIER view shows it."""
    cs = str(r.get("name") or "")
    p = [r.get("system_x"), r.get("system_y"), r.get("system_z")]
    if not cs or not all(isinstance(v, (int, float)) for v in p):
        return None
    names = {s.get("name") for s in r.get("services") or [] if isinstance(s, dict)}
    return {"callsign": cs, "system": r.get("system_name"), "id64": r.get("system_id64"),
            "pos": [float(v) for v in p], "updated": r.get("updated_at"),
            "access": r.get("carrier_docking_access") or None,
            "services": sorted({k for n, k in NEARBY_SERVICES.items() if n in names})}


def _with_distance(carriers: List[Dict[str, Any]], pos: Sequence[float]) -> List[Dict[str, Any]]:
    """The list with each carrier's distance from ``pos``, nearest first."""
    out = [dict(c, distance=round(math.dist(c["pos"], [float(v) for v in pos]), 2)) for c in carriers]
    return sorted(out, key=lambda c: c["distance"])
