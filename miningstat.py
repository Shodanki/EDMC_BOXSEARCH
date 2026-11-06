# -*- coding: utf-8 -*-
"""
miningstat.py - what a miner needs on the overlay, at most five lines
=====================================================================
Follows the mining events of the journal and Status.json and condenses them
to five lines for the cockpit overlay:

  ROCK     the last prospector report: target material share, content,
           a verdict against the best rock of the session, motherlode
  HOLD     ore on board, free space, limpets
  RATE     tonnes per hour over the last ten minutes, full in ~ minutes
  SESSION  refined this session, how long - in a ring this line becomes
  HOTSPOT  whether the hotspot is your target (then the game's own HUD
           compass points to its centre; the game gives no position in a
           ring, so nothing here can draw a map or a compass of its own)
  LIMPETS  how far the limpets go at the rate your session uses them,
           against the room left (a launched limpet frees its tonne)

Docking at a station or carrier ends the session (and the block).

Read only, no EDMC imports (testable on its own). The game writes nothing
about the refinery's bins - only each finished tonne (MiningRefined).
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

Line = Tuple[str, str]
GAP_S = 30 * 60            # a break this long starts a new session
ACTIVE_S = 10 * 60         # the overlay block shows this long after the last mining event
RATE_S = 10 * 60
DEFAULT_RATIO = 0.4        # limpets per refined tonne until the session says better
EVENTS = ("MiningRefined", "ProspectedAsteroid", "LaunchDrone", "AsteroidCracked", "Loadout", "Docked")
PLACE = ("SupercruiseExit", "SupercruiseEntry", "FSDJump", "Location")
COLOURS = {"head": "#3EF2E0", "data": "#7CFF6B", "warn": "#FFB23E", "new": "#B57CFF", "dim": "#8FA3A6"}


def _ts(e: Dict[str, Any]) -> float:
    try:
        return datetime.strptime(e.get("timestamp", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return time.time()


def type_key(s: Optional[str]) -> str:
    s = (s or "").strip().strip("$;").lower()
    if "#type=" in s:
        s = s.split("#type=", 1)[1].strip("$;")
    if s.endswith("_name"):
        s = s[:-5]
    return s.replace(" hotspot", "").replace("hotspot", "").replace(" ", "")


class MiningTracker:
    def __init__(self) -> None:
        self.reset()
        self.capacity = 0
        self.cargo: Dict[str, int] = {}
        self.target: Optional[str] = None
        self.target_name: Optional[str] = None
        self.ring: Optional[str] = None           # the ring you dropped into

    def reset(self) -> None:
        self.start = 0.0
        self.last = 0.0
        self.refined: Dict[str, int] = {}
        self.names: Dict[str, str] = {}
        self.ticks: Deque[float] = deque(maxlen=400)
        self.limpets_used = 0
        self.rock: Optional[Dict[str, Any]] = None
        self.best = 0.0
        self.ended = False

    # -- input ---------------------------------------------------------------
    def feed(self, e: Dict[str, Any], cargo: Optional[Dict[str, int]] = None) -> bool:
        """A journal event; True when the overlay block should be redrawn."""
        ev = e.get("event")
        if cargo is not None:
            self.cargo = {str(k).lower(): int(v or 0) for k, v in cargo.items()}
        if ev == "Loadout":
            self.capacity = int(e.get("CargoCapacity") or 0)
            return False
        if ev in PLACE:
            self.ring = (e.get("Body") if ev == "SupercruiseExit" and e.get("BodyType") == "PlanetaryRing"
                         else None)
            return bool(self.last)
        if ev not in EVENTS:
            return False
        if ev == "Docked":                    # at a station or carrier: the session is over
            changed = bool(self.last)
            self.last = 0.0
            self.ended = True
            return changed
        if ev == "LaunchDrone" and (e.get("Type") or "").lower() not in ("prospector", "collection"):
            return False                      # repair, fuel, research limpets are no mining
        t = _ts(e)
        if self.ended or (self.last and t - self.last > GAP_S):
            self.reset()                      # a new session after docking or a long break
        if not self.start:
            self.start = t
        self.last = t
        if ev == "MiningRefined":
            k = type_key(e.get("Type"))
            self.refined[k] = self.refined.get(k, 0) + 1
            self.names[k] = e.get("Type_Localised") or k.capitalize()
            self.ticks.append(t)
        elif ev == "LaunchDrone":
            self.limpets_used += 1
        elif ev == "ProspectedAsteroid":
            mats = [(type_key(m.get("Name")), m.get("Name_Localised") or m.get("Name") or "?",
                     float(m.get("Proportion") or 0)) for m in e.get("Materials") or []]
            content = (e.get("Content") or "").lower()
            self.rock = {"t": t, "mats": mats, "remaining": e.get("Remaining"),
                         "content": "high" if "high" in content else "medium" if "medium" in content else "low",
                         "motherlode": e.get("MotherlodeMaterial_Localised") or e.get("MotherlodeMaterial")}
            share = self._share(self.rock)
            self.rock["share"] = share
            self.rock["best_before"] = self.best
            self.best = max(self.best, share)
        return True

    def status(self, entry: Dict[str, Any]) -> None:
        """Status.json: the target hotspot ('Tritium Hotspot') sets the material."""
        if "Flags" not in entry:
            return
        dest = entry.get("Destination") or {}
        name = dest.get("Name_Localised") or dest.get("Name") or ""
        if "hotspot" in (dest.get("Name") or name).lower():
            self.target = type_key(dest.get("Name") or name) or None
            self.target_name = name
        else:
            self.target = self.target_name = None

    # -- derived -------------------------------------------------------------
    def key(self) -> Optional[str]:
        if self.target:
            return self.target
        if self.refined:
            return max(self.refined, key=self.refined.get)
        if self.rock and self.rock["mats"]:
            return max(self.rock["mats"], key=lambda m: m[2])[0]
        return None

    def _share(self, rock: Optional[Dict[str, Any]]) -> float:
        k = self.key()
        return max((p for mk, _n, p in (rock or {}).get("mats", []) if mk == k), default=0.0)

    def active(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return bool(self.last) and now - self.last <= ACTIVE_S

    def rate_h(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        n = sum(1 for t in self.ticks if now - t <= RATE_S)
        return round(n * 3600.0 / RATE_S)

    def ratio(self) -> float:
        total = sum(self.refined.values())
        return self.limpets_used / total if total >= 20 and self.limpets_used else DEFAULT_RATIO

    # -- the five lines ------------------------------------------------------
    def lines(self, now: Optional[float] = None, col: Optional[Dict[str, str]] = None) -> List[Line]:
        now = time.time() if now is None else now
        c = dict(COLOURS, **(col or {}))
        out: List[Line] = []
        k = self.key()
        r = self.rock
        if r:
            name = next((n for mk, n, _p in r["mats"] if mk == k), (self.names.get(k) or (k or "?").capitalize()))
            best = max(self.best, r["share"])
            verdict, colour = "", c["dim"]
            if best:
                if r["share"] >= 0.75 * best:
                    verdict, colour = "GOOD", c["data"]
                elif r["share"] < 0.4 * best:
                    verdict, colour = "MOVE ON", c["warn"]
                else:
                    verdict = "FAIR"
            txt = "ROCK  %s %.1f %% | %s" % (name, r["share"], r["content"])
            if verdict:
                txt += " | " + verdict
            if r.get("remaining") is not None and r["remaining"] < 100:
                txt += " | %d %% left" % round(r["remaining"])
            if r.get("motherlode"):
                txt += " | MOTHERLODE " + str(r["motherlode"])
                colour = c["new"]
            out.append((txt, colour))
        limpets = self.cargo.get("drones", 0)
        ore = sum(v for n, v in self.cargo.items() if n != "drones")
        free = max(0, self.capacity - ore - limpets) if self.capacity else None
        ratio = self.ratio()
        # every limpet launched frees its tonne: room for more ore than "free"
        room = int(free / (1.0 - ratio)) if free is not None and ratio < 1 else free
        reach = int(limpets / ratio) if ratio else 0
        hold = "HOLD  %d t ore" % ore
        if free is not None:
            hold += " | %d t free" % free
        hold += " | %d limpets" % limpets
        out.append((hold, c["warn"] if free is not None and self.capacity and free < 0.05 * self.capacity else c["data"]))
        rate = self.rate_h(now)
        if rate:
            txt = "RATE  %d t/h" % rate
            if room is not None:
                txt += " | full in ~%d min" % round(min(room, reach) / rate * 60)
            out.append((txt, c["data"]))
        else:
            out.append(("RATE  nothing refined in 10 min", c["dim"]))
        total = sum(self.refined.values())
        mins = max(1, round((now - self.start) / 60)) if self.start else 0
        main = max(self.refined, key=self.refined.get) if self.refined else None
        if self.ring and self.target:
            out.append(("HOTSPOT  %s targeted - HUD compass | %d t in %d min"
                        % (self.target_name or self.target, total, mins), c["head"]))
        elif self.ring:
            out.append(("HOTSPOT  not targeted - select it in the nav panel for the HUD compass", c["warn"]))
        else:
            out.append(("SESSION  %d t%s | %d min" % (total, (" " + self.names.get(main, "")) if main else "", mins), c["head"]))
        if room is not None and reach < room:
            out.append(("LIMPETS  last ~%d t - room for %d t" % (reach, room), c["warn"]))
        else:
            out.append(("LIMPETS  last ~%d t OK" % reach, c["dim"]))
        return out[:5]


def _selftest() -> int:
    """python miningstat.py - checks the lines with a short session."""
    m = MiningTracker()
    m.feed({"event": "Loadout", "CargoCapacity": 322})
    t0 = "2026-11-06T10:00:%02dZ"
    m.feed({"timestamp": t0 % 0, "event": "LaunchDrone", "Type": "Prospector"})
    m.feed({"timestamp": t0 % 5, "event": "ProspectedAsteroid", "Content": "$AsteroidMaterialContent_High;",
            "Materials": [{"Name": "Tritium", "Proportion": 31.5}, {"Name": "Water", "Proportion": 8}], "Remaining": 100})
    for i in range(10, 40, 3):
        m.feed({"timestamp": t0 % i, "event": "MiningRefined", "Type": "$tritium_name;", "Type_Localised": "Tritium"},
               cargo={"tritium": (i - 10) // 3 + 1, "drones": 120})
    m.status({"Flags": 1, "Destination": {"Name": "$SAA_RingHotspot:#type=$Tritium_name;;", "Name_Localised": "Tritium Hotspot"}})
    now = _ts({"timestamp": t0 % 59})
    lines = m.lines(now)
    # in the ring: the session line becomes the hotspot line
    m.feed({"timestamp": t0 % 50, "event": "SupercruiseExit", "Body": "X 4 B Ring", "BodyType": "PlanetaryRing"})
    ring_lines = m.lines(now)
    targeted = m.target
    m.status({"Flags": 1})                    # target dropped
    lost = m.lines(now)
    was_active = m.active(now)
    m.feed({"timestamp": t0 % 58, "event": "Docked", "StationType": "FleetCarrier"})
    docked_active = m.active(now)
    # undocked again: the next limpet starts a new session from zero
    m.feed({"timestamp": "2026-11-06T10:05:00Z", "event": "LaunchDrone", "Type": "Prospector"})
    fresh = sum(m.refined.values()) == 0 and m.limpets_used == 1
    fails = 0
    checks = [
        (len(lines) == 5, "five lines"),
        (lines[0][0].startswith("ROCK  Tritium 31.5 %") and "GOOD" in lines[0][0], "rock line"),
        ("HOLD  10 t ore | 192 t free | 120 limpets" == lines[1][0], "hold line: " + lines[1][0]),
        (lines[2][0].startswith("RATE  60 t/h"), "rate line: " + lines[2][0]),
        (lines[3][0].startswith("SESSION  10 t Tritium"), "session line"),
        (targeted == "tritium", "target from hotspot"),
        (was_active, "active"),
        (not docked_active, "docking ends the session"),
        (fresh, "a new session after docking"),
        (ring_lines[3][0].startswith("HOTSPOT  Tritium Hotspot targeted"), "hotspot line: " + ring_lines[3][0]),
        (lost[3][0].startswith("HOTSPOT  not targeted"), "hotspot lost: " + lost[3][0]),
        (len(lost) == 5, "still five lines"),
    ]
    for ok, what in checks:
        if not ok:
            fails += 1
            print("FAIL", what)
    print("miningstat selftest: %d failures" % fails)
    for ln in lines:
        print("  ", ln[0])
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
