# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
miningstat.py - what a miner needs on the overlay, at most five lines
=====================================================================
Follows the mining events of the journal and Status.json and condenses them
to five lines for the cockpit overlay:

  ROCK     the last prospector report: target material share, content,
           a verdict against the best rock of the session, motherlode -
           and (5.0, MP1) the tonnes such a rock gave you before
  HOLD     limpets, ore on board, free space
  RATE     tonnes per hour over the last ten minutes, limpets per tonne
  SESSION  refined this session, how long, full in ~ minutes - in a ring this line becomes
  HOTSPOT  whether the hotspot is your target (then the game's own HUD
           compass points to its centre; the game gives no position in a
           ring, so nothing here can draw a map or a compass of its own)
  LIMPETS  how far the limpets go at the rate your session uses them,
           against the room left (a launched limpet frees its tonne); with
           the hold filling up, the limpets more than it still needs - ore
           you would leave behind

Only a prospector limpet starts a session - collectors serve other work too
(refining alone - the
Rhino SRV's ground mining, the refinery's last tonnes after docking - does
not). Docking at a station or carrier or a hyperspace jump ends it.

Read only, no EDMC imports (testable on its own). The game writes nothing
about the refinery's bins - only each finished tonne (MiningRefined).
"""

from __future__ import annotations

import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

Line = Tuple[str, str]
GAP_S = 30 * 60            # a break this long starts a new session
ACTIVE_S = 10 * 60         # the overlay block shows this long after the last mining event
RATE_S = 10 * 60
DEFAULT_RATIO = 0.4        # limpets per refined tonne until the session says better
MIN_LIMPETS = 5            # kept back: one more rock (15.11.2026: 1.2 prospectors and 2.6
#                            collectors per rock mined)
SPARE_WHEN = 0.25          # spare limpets are named once the free space is down to this share
EVENTS = ("MiningRefined", "ProspectedAsteroid", "LaunchDrone", "AsteroidCracked", "Loadout", "Docked")
MINING_TOOLS = ("hpt_mininglaser", "hpt_mining_", "hpt_mrascanner", "int_refinery")
PLACE = ("SupercruiseExit", "SupercruiseEntry", "FSDJump", "Location")
COLOURS = {"head": "#3EF2E0", "data": "#7CFF6B", "warn": "#FFB23E", "new": "#B57CFF", "dim": "#8FA3A6"}


def _ts(e: Dict[str, Any]) -> float:
    try:
        return datetime.strptime(e.get("timestamp", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return time.time()


def type_key(s: Optional[str]) -> str:
    """A material's internal key from a journal name, a hotspot type or a label
    - lower case, no 'hotspot', no blanks."""
    s = (s or "").strip().strip("$;").lower()
    if "#type=" in s:
        s = s.split("#type=", 1)[1].strip("$;")
    if s.endswith("_name"):
        s = s[:-5]
    return s.replace(" hotspot", "").replace("hotspot", "").replace(" ", "")


# MP1 (5.0): tonnes a mined rock gave, by the share of its main material.
# Measured on the developer's journals, 17.11.2026 (246 mined rocks of 309
# prospected): under 10 % median 4 t (2-6, n 116), 10-25 % 10 t (7-13,
# n 99), 25 % and more 14 t (11-18, n 31); the content level hardly
# matters next to the share.
YIELD_BINS = (10.0, 25.0)
YIELD_MIN_N = 5
YIELD_END = ("Docked", "FSDJump", "SupercruiseEntry", "LoadGame", "Died", "Shutdown")


class RockYield:
    """
    MP1: what a prospected rock gave - the tonnes refined until the next
    prospector report or the end of the session, of the rock's main
    refined material, against that material's share. Rocks left without a
    tonne do not count; tonnes refined in a surface vehicle neither.
    expect(share) gives median and middle half of the rocks like it.
    """

    def __init__(self) -> None:
        self.bins: Dict[int, List[int]] = {}
        self._rock: Optional[Dict[str, float]] = None
        self._got: Dict[str, int] = {}
        self._vehicle = False

    @staticmethod
    def _bin(share: float) -> int:
        return sum(1 for b in YIELD_BINS if share >= b)

    def _close(self) -> None:
        if self._rock is not None and self._got:
            main = max(self._got, key=self._got.get)
            self.bins.setdefault(self._bin(self._rock.get(main, 0.0)), []).append(self._got[main])
            for v in self.bins.values():
                del v[:-400]
        self._rock, self._got = None, {}

    def feed(self, e: Dict[str, Any]) -> None:
        """One journal event."""
        ev = e.get("event")
        if ev in ("LaunchSRV", "LaunchVessel"):
            self._vehicle = True
        elif ev in ("DockSRV", "DockVessel", "SRVDestroyed"):
            self._vehicle = False
        elif ev == "ProspectedAsteroid":
            self._close()
            self._rock = {type_key(m.get("Name")): float(m.get("Proportion") or 0) for m in e.get("Materials") or []}
        elif ev == "MiningRefined" and self._rock is not None and not self._vehicle:
            k = type_key(e.get("Type"))
            self._got[k] = self._got.get(k, 0) + 1
        elif ev in YIELD_END:
            self._close()

    def expect(self, share: float) -> Optional[Dict[str, int]]:
        """{"t": median, "lo", "hi" (middle half), "n"} for rocks of this
        share, None below YIELD_MIN_N rocks."""
        xs = sorted(self.bins.get(self._bin(share), []))
        n = len(xs)
        if n < YIELD_MIN_N:
            return None
        med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
        return {"t": int(round(med)), "lo": xs[n // 4], "hi": xs[(3 * n) // 4], "n": n}


class MiningTracker:
    """One mining session from the journal: last prospected rock, refined
    tonnes, rate, limpets - the mining block of the overlay."""
    def __init__(self) -> None:
        self.reset()
        self.capacity = 0
        self.cargo: Dict[str, int] = {}
        self.target: Optional[str] = None
        self.target_name: Optional[str] = None
        self.ring: Optional[str] = None           # the ring you dropped into
        self.miner: Optional[bool] = None         # ship has mining tools (None: no Loadout yet)
        self.yields = RockYield()                 # MP1: tonnes per rock, learnt across sessions

    def reset(self) -> None:
        """Start a new session (the hold and the capacity stay)."""
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
        self.yields.feed(e)
        if cargo is not None:
            self.cargo = {str(k).lower(): int(v or 0) for k, v in cargo.items()}
        if ev == "Loadout":
            self.capacity = int(e.get("CargoCapacity") or 0)
            # a mining ship carries mining tools; a collector limpet out of an
            # explorer (picking up cargo) is no mining
            mods = e.get("Modules")
            self.miner = (any(str(m.get("Item") or "").lower().startswith(MINING_TOOLS) for m in mods)
                          if mods else None)
            return False
        if ev in PLACE:
            self.ring = (e.get("Body") if ev == "SupercruiseExit" and e.get("BodyType") == "PlanetaryRing"
                         else None)
            if ev == "FSDJump":               # a jump: navigating now, mining is over
                changed = bool(self.last)
                self.last = 0.0
                self.ended = True
                return changed
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
        # only a prospector or collector limpet starts a session: refining
        # alone - ground mining in the Rhino SRV, the last tonnes in the
        # refinery after docking - is no mining-ship session (07.11.2026:
        # 44 t Tantalum/Thorium from a Rhino out of an explorer)
        # collector limpets serve other work too (cargo, escape pods): only a
        # prospector - which every mining run begins with - starts a session
        armed = ((ev == "LaunchDrone" and (e.get("Type") or "").lower() == "prospector")
                 or ev == "ProspectedAsteroid") and self.miner is not False
        if self.ended or (self.last and t - self.last > GAP_S):
            if not armed:
                return False
            self.reset()                      # a new session after docking, a jump or a long break
        if not self.start:
            if not armed:
                return False
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
        """The material the block follows: the chosen target, else the most
        refined, else the richest in the last rock."""
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
        """True while the last mining event is no older than ACTIVE_S."""
        now = time.time() if now is None else now
        return bool(self.last) and now - self.last <= ACTIVE_S

    def rate_h(self, now: Optional[float] = None) -> int:
        """Refined tonnes per hour over the last RATE_S seconds."""
        now = time.time() if now is None else now
        n = sum(1 for t in self.ticks if now - t <= RATE_S)
        return round(n * 3600.0 / RATE_S)

    def ratio(self) -> float:
        """Limpets used per refined tonne - measured after 20 t, else the
        default."""
        total = sum(self.refined.values())
        return self.limpets_used / total if total >= 20 and self.limpets_used else DEFAULT_RATIO

    # -- the five lines ------------------------------------------------------
    def lines(self, now: Optional[float] = None, col: Optional[Dict[str, str]] = None) -> List[Line]:
        """The mining block as (text, colour) lines, at most five: rock, hold
        (limpets, ore, free), rate, session with "full in", limpets."""
        now = time.time() if now is None else now
        c = dict(COLOURS, **(col or {}))
        out: List[Line] = []
        if self.rock:
            out.append(self._rock_line(c))
        h = self.hold()
        hold = "HOLD  %d limpets | %d t ore" % (h["limpets"], h["ore"])
        if h["free"] is not None:
            hold += " | %d t free" % h["free"]
        tight = h["free"] is not None and self.capacity and h["free"] < 0.05 * self.capacity
        out.append((hold, c["warn"] if tight else c["data"]))
        rate = self.rate_h(now)
        full = None
        if rate:
            out.append(("RATE  %d t/h | %.2f limpets/t" % (rate, h["ratio"]), c["data"]))
            if h["room"] is not None:
                full = round(min(h["room"], h["reach"]) / rate * 60)
        else:
            out.append(("RATE  nothing refined in 10 min", c["dim"]))
        out.append(self._session_line(now, full, c))
        out.append(self._limpet_line(h, c))
        return out[:5]

    def _rock_line(self, c: Dict[str, str]) -> Line:
        """ROCK: the last prospected asteroid against the best of the session."""
        k, r = self.key(), self.rock or {}
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
        exp = self.yields.expect(r["share"])
        if exp:
            txt += " | ~%d t (%d-%d)" % (exp["t"], exp["lo"], exp["hi"])
        if r.get("motherlode"):
            txt += " | MOTHERLODE " + str(r["motherlode"])
            colour = c["new"]
        return txt, colour

    def hold(self) -> Dict[str, Any]:
        """The hold now: limpets, ore, free (None without the capacity), the
        ore that still fits (a launched limpet frees its tonne), how far the
        limpets go, and the limpets more than that needs (spare)."""
        limpets = self.cargo.get("drones", 0)
        ore = sum(v for n, v in self.cargo.items() if n != "drones")
        free = max(0, self.capacity - ore - limpets) if self.capacity else None
        ratio = self.ratio()
        room = int(free / (1.0 - ratio)) if free is not None and ratio < 1 else free
        reach = int(limpets / ratio) if ratio else 0
        spare = None
        if room is not None:
            spare = max(0, limpets - int(math.ceil(ratio * room)) - MIN_LIMPETS)
        return {"limpets": limpets, "ore": ore, "free": free, "ratio": ratio, "room": room,
                "reach": reach, "spare": spare}

    def _session_line(self, now: float, full: Optional[int], c: Dict[str, str]) -> Line:
        """SESSION or, in a ring, HOTSPOT: tonnes, minutes, full in."""
        total = sum(self.refined.values())
        mins = max(1, round((now - self.start) / 60)) if self.start else 0
        tail = " | full ~%d min" % full if full is not None else ""
        if self.ring and self.target:
            return ("HOTSPOT  %s targeted | %d t in %d min%s"
                    % (self.target_name or self.target, total, mins, tail), c["head"])
        if self.ring:
            return ("HOTSPOT  not targeted (nav panel) | %d t in %d min%s" % (total, mins, tail), c["warn"])
        main = max(self.refined, key=self.refined.get) if self.refined else None
        what = (" " + self.names.get(main, "")) if main else ""
        return "SESSION  %d t%s | %d min%s" % (total, what, mins, tail), c["head"]

    def _limpet_line(self, h: Dict[str, Any], c: Dict[str, str]) -> Line:
        """LIMPETS: too few for the room left - or, with the hold filling up,
        more than it needs: those tonnes are ore you leave behind (15.11.2026:
        the hold full with 43 limpets aboard)."""
        if h["room"] is not None and h["reach"] < h["room"]:
            return "LIMPETS  last ~%d t - room for %d t" % (h["reach"], h["room"]), c["warn"]
        filling = h["free"] is not None and self.capacity and h["free"] <= SPARE_WHEN * self.capacity
        if filling and h["spare"] and h["spare"] >= MIN_LIMPETS:
            return ("LIMPETS  ~%d spare - eject them for ~%d t more ore" % (h["spare"], h["spare"]),
                    c["warn"])
        return "LIMPETS  last ~%d t OK" % h["reach"], c["dim"]
