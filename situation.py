# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12: the cockpit overlay's situation column - short facts the game's own
HUD does not show, each only while it matters.

A Board holds items (key -> lines, priority, until): warnings first, then
tasks, then information; an item goes when its time runs out. The text
builders below turn plain facts into at most a few lines each:

  hazard    the star you arrived at can hurt (neutron, white dwarf, black hole)
  risk      unsold data at stake while in danger
  carrier   your carrier's jump: countdown, distance, tritium
  route     fuel along the plotted route
  landing   approaching a body: gravity, temperature, atmosphere, biology
            (open genera by what you were paid for them), finds there
  system    what the system's scanned bodies are worth, what mapping adds
  ring      a ring's hotspots, what you sold that material for
  boxel     the boxel you arrived in: how much of it is known
  session   what this session brought - after a sale or on docking

Plain Python, no EDMC: tested on its own.
"""

from __future__ import annotations

import calendar
import math
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Line = Tuple[str, str]
MAX_LINES = 9
LINE_MAX = 44            # characters, as the other overlay blocks

# what goes first: warnings, then tasks, then information
PRIORITY = {"journal": 2, "hazard": 5, "risk": 8, "carrier": 20, "route": 25, "landing": 30, "system": 50,
            "spot": 52, "ring": 55, "boxel": 60, "session": 70}
COL = {"head": "#3EF2E0", "data": "#7CFF6B", "warn": "#FFB23E", "alert": "#FF4D4D",
       "new": "#B57CFF", "dim": "#8FA3A6"}
HIGH_G, VERY_HIGH_G = 2.0, 3.0          # as the FIS's PLANET INFO
HOT_K, COLD_K = 800.0, 60.0
G0 = 9.80665


def cr(v: Optional[float]) -> str:
    """Credits short: 950 k, 18.4 M, 1.2 G."""
    v = float(v or 0)
    if v >= 1e9:
        return "%.1f G" % (v / 1e9)
    if v >= 1e6:
        return "%.1f M" % (v / 1e6)
    if v >= 1e3:
        return "%.0f k" % (v / 1e3)
    return "%.0f" % v


class Board:
    """The items of the situation column."""

    def __init__(self) -> None:
        self.items: Dict[str, Tuple[int, List[Line], float]] = {}
        self.rev = 0

    def put(self, key: str, lines: Sequence[Line], ttl: float, now: float,
            prio: Optional[int] = None) -> None:
        """Show an item for ttl seconds (replacing what it said)."""
        if not lines:
            self.drop(key)
            return
        self.items[key] = (PRIORITY.get(key, 90) if prio is None else prio, list(lines), now + ttl)
        self.rev += 1

    def refresh(self, key: str, lines: Sequence[Line]) -> bool:
        """New lines for an item on show, its time left unchanged; False
        when it is not on show."""
        it = self.items.get(key)
        if it is None:
            return False
        if list(lines) != it[1]:
            self.items[key] = (it[0], list(lines), it[2]) if lines else it
            self.rev += 1
        return True

    def has(self, key: str) -> bool:
        """The item is on the board."""
        return key in self.items

    def drop(self, key: str) -> None:
        """Take an item away."""
        if self.items.pop(key, None) is not None:
            self.rev += 1

    def lines(self, now: float, enabled: Optional[Iterable[str]] = None) -> List[Line]:
        """What the column shows now: items by priority, expired ones gone,
        at most MAX_LINES lines; only the keys enabled (None: all)."""
        for k in [k for k, (_p, _ls, until) in self.items.items() if until <= now]:
            self.drop(k)
        keys = set(enabled) if enabled is not None else None
        out: List[Line] = []
        for _p, k in sorted((p, k) for k, (p, _ls, _u) in self.items.items()):
            if keys is not None and k not in keys:
                continue
            ls = self.items[k][1]
            if out and len(out) + len(ls) > MAX_LINES:
                continue
            out += ls
        return out[:MAX_LINES]


# ---------------------------------------------------------------------------
# text builders
# ---------------------------------------------------------------------------
# Every line fits LINE_MAX characters, like the other overlay blocks - the
# column stands in the right half of the 1280-wide canvas.

def journal_gap_lines(added: int) -> List[Line]:
    """4.12.1: EDMC passes on no journal events (journalgap) - the plugin
    stores the missed ones itself, but only a restart brings EDMC back."""
    return [("! EDMC GETS NO JOURNAL EVENTS", COL["alert"]),
            (("  restart EDMC - %d missed ones stored" % added)[:LINE_MAX], COL["warn"])]


def hazard_lines(star_type: Optional[str]) -> List[Line]:
    """The arrival star can hurt: neutron star, white dwarf, black hole."""
    st = star_type or ""
    if st == "N":
        return [("! NEUTRON STAR ahead - jet cones hurt", COL["alert"]),
                ("  keep clear of the cones on the way in", COL["warn"])]
    if st.startswith("D"):
        return [("! WHITE DWARF ahead - jet cones hurt", COL["warn"])]
    if st in ("H", "SupermassiveBlackHole"):
        return [("! BLACK HOLE ahead - no fuel scoop there", COL["warn"])]
    return []


def risk_lines(unsold: Dict[str, Any], why: str, vouchers: Optional[Dict[str, Any]] = None) -> List[Line]:
    """Unsold data and unredeemed vouchers (ST13) at stake: shown while in
    danger (why: what happened)."""
    data = bool(unsold and (unsold.get("bodies") or unsold.get("species")))
    held = (vouchers or {}).get("total") or 0
    if not data and not held:
        return []
    out = [(("RISK  %s - at stake ~%s Cr" % (why, cr((unsold or {}).get("value", 0) * data + held)))[:LINE_MAX],
            COL["alert"])]
    if data:
        n = unsold.get("systems", 0)
        bits = ["%d system%s" % (n, "" if n == 1 else "s"), "%d bodies" % unsold.get("bodies", 0)]
        if unsold.get("first"):
            bits.append("%d first" % unsold["first"])
        if unsold.get("species"):
            bits.append("%d species" % unsold["species"])
        out.append((("      " + " · ".join(bits))[:LINE_MAX], COL["warn"]))
    if held:
        kinds = [("bounty", "bounties"), ("bonds", "bonds"), ("codex", "codex")]
        bits = ["%s %s" % (label, cr(vouchers[k])) for k, label in kinds if vouchers.get(k)]
        out.append((("      vouchers: " + " · ".join(bits))[:LINE_MAX], COL["warn"]))
    return out


def carrier_lines(dest: str, departure: Optional[float], now: float, ly: Optional[float] = None,
                  tritium: Optional[int] = None, tank: Optional[int] = None) -> List[Line]:
    """The own carrier's jump: countdown, where to, distance and tritium."""
    if departure is None:
        return []
    left = departure - now
    if left < -120:
        return []
    when = "jumping" if left <= 0 else "%d:%02d" % (int(left) // 60, int(left) % 60)
    out = [("CARRIER  %s  -> %s" % (when, (dest or "?")[:24]), COL["warn"] if 0 < left <= 120 else COL["head"])]
    bits = []
    if ly:
        bits.append("%.0f ly" % ly)
    if tritium is not None:
        bits.append("needs ~%d t" % tritium)
    if tank is not None:
        bits.append("has %d t" % tank)
    if bits:
        short = tritium is not None and tank is not None and tritium > tank
        out.append(("         " + " · ".join(bits), COL["alert"] if short else COL["dim"]))
    return out


def route_lines(jumps: int, fuel_line: Optional[Tuple[str, str]]) -> List[Line]:
    """Fuel along the plotted route (deepspace.scoop_line)."""
    if not fuel_line or jumps < 2:
        return []
    text, level = fuel_line
    col = {"alert": COL["alert"], "warn": COL["warn"]}.get(level, COL["data"])
    return [("ROUTE  %d jumps plotted" % jumps, COL["head"]), (text[:LINE_MAX], col)]


def route_find_line(unknown: int, hops: int) -> List[Line]:
    """F5 (5.1.0): hops of the plotted route no database knows - a first
    discovery possible in passing, at no extra flight."""
    if hops < 1 or unknown < 1:
        return []
    return [(("      %d of %d in no database: first finds" % (unknown, hops))[:LINE_MAX], COL["new"])]


def _bio_lines(open_genera: Sequence[Tuple[str, Optional[float]]]) -> List[Line]:
    """Open genera by the best price paid for them so far, two a line."""
    if not open_genera:
        return []
    ranked = sorted(open_genera, key=lambda g: -(g[1] or 0))
    parts = ["%s %s" % (n[:16], cr(v)) if v else n[:28] for n, v in ranked[:4]]
    col = COL["new"] if ranked[0][1] else COL["data"]
    out = [(("BIO  " + " · ".join(parts[:2]))[:LINE_MAX], col)]
    if len(parts) > 2:
        more = " +%d" % (len(ranked) - 4) if len(ranked) > 4 else ""
        out.append((("     " + " · ".join(parts[2:]) + more)[:LINE_MAX], col))
    return out


def landing_lines(body: Dict[str, Any]) -> List[Line]:
    """Approaching a body: gravity, temperature, atmosphere; biology open
    (best paid first); what else was found there."""
    g, t = body.get("gravity_g"), body.get("temp_k")
    name = (body.get("short") or body.get("name") or "?")[:20]
    gtxt = (" %.2f g%s" % (g, " !" if g >= HIGH_G else "")) if g is not None else ""
    hot = t is not None and (t >= HOT_K or t <= COLD_K)
    tone = COL["alert"] if g is not None and g >= VERY_HIGH_G else \
        COL["warn"] if (g is not None and g >= HIGH_G) or hot else COL["head"]
    out = [(("LANDING  %s%s" % (name, gtxt))[:LINE_MAX], tone)]
    bits = []
    if t is not None:
        bits.append("%.0f K%s" % (t, " !" if hot else ""))
    if body.get("atmosphere"):
        bits.append(str(body["atmosphere"]))
    if bits:
        out.append((("         " + " · ".join(bits))[:LINE_MAX], COL["warn"] if hot else COL["dim"]))
    out += _bio_lines(body.get("open_genera") or [])
    if not body.get("open_genera") and body.get("bio_done"):
        out.append(("BIO  all species done here", COL["dim"]))
    finds = body.get("finds") or []
    if finds:
        out.append((("FINDS  " + " · ".join(finds[:3]))[:LINE_MAX], COL["new"]))
    return out


NOTABLE_SHORT = {"Earthlike body": "ELW", "Water world": "WW", "Ammonia world": "AW",
                 "terraformable": "terraformable"}


def system_lines(s: Dict[str, Any]) -> List[Line]:
    """What the scanned bodies are worth, and what mapping adds."""
    if not s or not s.get("scanned"):
        return []
    of = ("/%d" % s["body_count"]) if s.get("body_count") else ""
    head = "SYSTEM  %d%s scanned · ~%s Cr" % (s["scanned"], of, cr(s["value"]))
    if s.get("new"):
        head += " · %d new" % s["new"]
    out = [(head[:LINE_MAX], COL["new"] if s.get("new") else COL["head"])]
    nb = s.get("notable") or {}
    if nb:
        txt = " · ".join("%d %s" % (n, NOTABLE_SHORT.get(k, k)) for k, n in sorted(nb.items()))
        out.append((("*  " + txt)[:LINE_MAX], COL["new"]))
    if s.get("to_map"):
        fm = " · %d first" % s["first_map"] if s.get("first_map") else ""
        out.append((("DSS  %d to map ~+%s Cr%s" % (s["to_map"], cr(s["map_gain"]), fm))[:LINE_MAX], COL["data"]))
    return out


def ring_lines(ring: str, hotspots: Sequence[Tuple[str, int]], prices: Dict[str, float]) -> List[Line]:
    """A ring's hotspots, with the last price you sold each material for."""
    if not hotspots:
        return []
    n = sum(c for _m, c in hotspots)
    out = [(("RING  %s · %d hotspot%s" % (ring[-16:], n, "" if n == 1 else "s"))[:LINE_MAX], COL["head"])]
    for m, c in hotspots[:3]:
        p = prices.get(m.lower())
        sold = " · sold %s/t" % cr(p) if p else ""
        out.append((("      %s x%d%s" % (m[:22], c, sold))[:LINE_MAX], COL["data"]))
    return out


SPOT_COL = {"good": "data", "poor": "warn", "fair": "dim", "open": "dim"}


def spot_lines(ring: str, material: str, odds: Optional[Dict[str, Any]], field: Optional[Dict[str, Any]],
               loaded: bool = True) -> List[Line]:
    """SP2 (5.1.0): a ring hotspot set as target - the chance of a good
    field (MP4) and what you got there before (MP3), at a glance."""
    if not ring or not material:
        return []
    out = [(("SPOT  %s · %s" % (material[:18], ring[-20:]))[:LINE_MAX], COL["head"])]
    if not loaded:
        return out + [("      fields still counting ...", COL["dim"])]
    p = (odds or {}).get("p")
    if p is None:
        out.append((("      chance: learning · %d of %d fields" % ((odds or {}).get("n", 0), 3))[:LINE_MAX],
                    COL["dim"]))
    else:
        v = odds.get("verdict")
        col = "dim" if odds.get("thin") else SPOT_COL.get(v or "", "dim")
        out.append((("      %d %% good field · from %d fields" % (round(100 * p), odds["n"]))[:LINE_MAX], COL[col]))
    if field and field.get("rating"):
        pg = field.get("per_good")
        bits = [field["rating"], ("%.1f prosp/good" % pg) if pg is not None else "no good rock",
                ("%.0f %% avg" % field["mean_share"]) if field.get("mean_share") is not None else ""]
        out.append((("      you: " + " · ".join(b for b in bits if b))[:LINE_MAX],
                    COL[SPOT_COL.get(field["rating"], "dim")]))
    else:
        out.append(("      not mined here yet", COL["dim"]))
    return out


def boxel_lines(prefix: str, known: int, end: Optional[int], probes: int) -> List[Line]:
    """The boxel you arrived in: how many of its systems are known."""
    if not prefix:
        return []
    short = " ".join(prefix.split()[-2:])
    tail = (" · ends at %d" % end) if end is not None else ""
    out = [(("BOXEL  %s · %d known%s" % (short, known, tail))[:LINE_MAX], COL["dim"])]
    if probes:
        out.append(("       %d name%s to check in the galaxy map" % (probes, "" if probes == 1 else "s"),
                    COL["warn"]))
    return out


def session_lines(s: Dict[str, Any], sold: Optional[int] = None) -> List[Line]:
    """What this session brought (a sale or docking shows it)."""
    if not s or not (s.get("jumps") or s.get("scanned") or s.get("species") or sold):
        return []
    out = []
    if sold:
        out.append(("SOLD  %s Cr - well done" % cr(sold), COL["data"]))
    tally = (s.get("jumps", 0), s.get("scanned", 0), s.get("mapped", 0))
    out.append(("SESSION  %d jumps · %d bodies · %d maps" % tally, COL["head"]))
    bits = []
    if s.get("first"):
        bits.append("%d first discoveries" % s["first"])
    if s.get("species"):
        bits.append("%d species" % s["species"])
    if bits:
        out.append(("         " + " · ".join(bits), COL["new"]))
    if s.get("earned"):
        out.append(("         earned %s Cr" % cr(s["earned"]), COL["data"]))
    return out


# ---------------------------------------------------------------------------
# what the column learns from the journal (no EDMC, no database)
# ---------------------------------------------------------------------------

DANGER_FLAGS = {1 << 22: "in danger", 1 << 23: "interdiction", 1 << 20: "overheating"}
SELL_EVENTS = ("SellExplorationData", "MultiSellExplorationData", "SellOrganicData", "MarketSell")


def iso_time(stamp: Any) -> Optional[float]:
    """Journal timestamp (UTC) to seconds, None when it is not one."""
    try:
        return float(calendar.timegm(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError):
        return None


def sold_of(e: Dict[str, Any]) -> int:
    """Credits a sale brought (exploration, organic, market)."""
    ev = e.get("event")
    if ev in ("SellExplorationData", "MultiSellExplorationData"):
        return int(e.get("TotalEarnings") or (int(e.get("BaseValue") or 0) + int(e.get("Bonus") or 0)))
    if ev == "SellOrganicData":
        return sum(int(b.get("Value") or 0) + int(b.get("Bonus") or 0) for b in e.get("BioData") or [])
    if ev == "MarketSell":
        return int(e.get("TotalSale") or 0)
    return 0


def danger_why(flags: int) -> Optional[str]:
    """What a Status.json Flags value says is threatening, or None."""
    for bit, why in DANGER_FLAGS.items():
        if flags & bit:
            return why
    return None


def tritium_t(ly: float, used_t: Optional[int]) -> int:
    """A carrier jump's tritium, from the formula players worked out from
    the game (about): 5 t plus the distance times (25000 + the carrier's
    used capacity) / 200000."""
    return int(math.ceil(5 + float(ly) * (25000 + int(used_t or 0)) / 200000.0))


def genus_open(genera: Sequence[str], analysed: Sequence[Any]) -> List[str]:
    """Genera of a body none of whose species you analysed there.

    analysed: species names, or the database's entries {"species", "genus"}
    (bio_species) - those reached this as dicts and stopped the landing
    card of every body with a species analysed (found 17.11.2026)."""
    done = [str((s.get("species") or s.get("genus") or "") if isinstance(s, dict) else s).lower()
            for s in analysed]
    out = []
    for g in genera:
        stem = g.lower().rstrip("s")
        if not any(stem in s for s in done):
            out.append(g)
    return out


class Session:
    """This game session (since the last LoadGame): jumps, bodies, maps,
    species, what the sales brought."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """A new session (LoadGame)."""
        self.jumps = self.scanned = self.first = self.mapped = self.species = self.earned = 0
        self._seen: set = set()

    def feed(self, e: Dict[str, Any]) -> int:
        """One event; returns what a sale brought (0 otherwise)."""
        ev = e.get("event")
        if ev == "LoadGame":
            self.reset()
        elif ev == "FSDJump":
            self.jumps += 1
        elif ev == "Scan" and e.get("ScanType") != "NavBeaconDetail":
            key = (e.get("SystemAddress"), e.get("BodyID"))
            if key not in self._seen:
                self._seen.add(key)
                self.scanned += 1
                self.first += 1 if e.get("WasDiscovered") is False else 0
        elif ev == "SAAScanComplete":
            self.mapped += 1
        elif ev == "ScanOrganic" and e.get("ScanType") == "Analyse":
            self.species += 1
        elif ev in SELL_EVENTS:
            got = sold_of(e)
            self.earned += got
            return got
        return 0

    def summary(self) -> Dict[str, Any]:
        """The tally for session_lines."""
        return {"jumps": self.jumps, "scanned": self.scanned, "first": self.first,
                "mapped": self.mapped, "species": self.species, "earned": self.earned}


class Prices:
    """What you were paid: per genus and species (organic data), per
    commodity (market sales, newest wins)."""

    def __init__(self) -> None:
        self.genus: Dict[str, int] = {}
        self.species: Dict[str, int] = {}
        self.market: Dict[str, float] = {}

    def feed(self, e: Dict[str, Any]) -> None:
        """SellOrganicData and MarketSell; the rest is ignored."""
        ev = e.get("event")
        if ev == "SellOrganicData":
            for b in e.get("BioData") or []:
                v = int(b.get("Value") or 0)
                g = b.get("Genus_Localised") or b.get("Genus") or ""
                s = b.get("Species_Localised") or b.get("Species") or ""
                if g and v:
                    self.genus[g] = max(v, self.genus.get(g, 0))
                if s and v:
                    self.species[s] = v
        elif ev == "MarketSell" and e.get("Type") and e.get("SellPrice"):
            self.market[str(e["Type"]).lower()] = float(e["SellPrice"])

    def of_genus(self, genus: str) -> Optional[int]:
        """The best you were paid for a species of this genus."""
        return self.genus.get(genus)


class Scans:
    """What the detailed scans say that the database does not keep: mass,
    gravity, temperature, atmosphere; the honk's body count."""

    MAX = 4000

    def __init__(self) -> None:
        self.bodies: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
        self.body_count: Dict[Any, int] = {}

    def feed(self, e: Dict[str, Any]) -> None:
        """Scan and FSSDiscoveryScan; the rest is ignored."""
        ev = e.get("event")
        if ev == "FSSDiscoveryScan" and e.get("SystemAddress"):
            self.body_count[e["SystemAddress"]] = int(e.get("BodyCount") or 0)
        elif ev == "Scan" and e.get("BodyID") is not None:
            g = e.get("SurfaceGravity")
            self.bodies[(e.get("SystemAddress"), e.get("BodyID"))] = {
                "name": e.get("BodyName"), "mass_em": e.get("MassEM"), "stellar_mass": e.get("StellarMass"),
                "gravity_g": (float(g) / G0) if g is not None else None,
                "temp_k": e.get("SurfaceTemperature"), "landable": e.get("Landable"),
                "atmosphere": e.get("Atmosphere") or None}
            if len(self.bodies) > self.MAX:
                for k in list(self.bodies)[: len(self.bodies) - self.MAX]:
                    del self.bodies[k]

    def of(self, sys_id64: Any, body_id: Any) -> Dict[str, Any]:
        """What is known of one body (empty dict: nothing)."""
        return self.bodies.get((sys_id64, body_id)) or {}


class CarrierWatch:
    """Your carrier's next jump (CarrierJumpRequest) and what it carries
    (CarrierStats: tritium in the tank, used capacity)."""

    def __init__(self) -> None:
        self.dest: Optional[str] = None
        self.departure: Optional[float] = None
        self.requested: Optional[float] = None
        self.fuel: Optional[int] = None
        self.used: Optional[int] = None

    def feed(self, e: Dict[str, Any]) -> bool:
        """True when the jump changed (set, cancelled, done)."""
        ev = e.get("event")
        if ev == "CarrierStats":
            self.fuel = e.get("FuelLevel")
            su = e.get("SpaceUsage") or {}
            if su.get("TotalCapacity") is not None and su.get("FreeSpace") is not None:
                self.used = int(su["TotalCapacity"]) - int(su["FreeSpace"])
            return False
        if ev == "CarrierJumpRequest":
            self.dest = e.get("SystemName")
            self.departure = iso_time(e.get("DepartureTime"))
            self.requested = iso_time(e.get("timestamp"))
            return True
        if ev in ("CarrierJumpCancelled", "CarrierJump") and self.departure is not None:
            self.dest = self.departure = self.requested = None
            return True
        return False

    def pending(self, now: float) -> bool:
        """A jump is announced and not long past."""
        return self.departure is not None and now - self.departure < 120
