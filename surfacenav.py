# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
surfacenav.py - where things are on a body, seen from where you are
====================================================================
Pure functions over the surface marks the plugin records (touchdown,
vehicle parked, exobiology samples, codex finds, screenshots ...):

  body_state()     what is still open on a body: the parked SRV, the parked
                   ship, species logged but not analysed (with the number of
                   samples taken), and points worth coming back to
  bearing_deg()    initial great-circle bearing from one fix to another
  compass_lines()  the cockpit-overlay block: distance, absolute course
                   ("brg 255", to compare with the game's compass) and the
                   turn relative to your heading for each of those points;
                   species lost in a crash say "lost - redo", not "done"

Display only. Positions come from the game's own Status.json, which reports
latitude/longitude on the surface and in orbital cruise alike - so the same
block also works as "known points" on the way down from orbit.

No EDMC imports, so it can be tested on its own and the FIS can use it too.
"""

from __future__ import annotations

import calendar
import math
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Line = Tuple[str, str]

# kinds worth finding again (sites stay where they are; bio colonies too)
SITE_KINDS = ("codex", "settlement", "screenshot")
SITE_MERGE_M = 60.0          # two finds this close count as one point


def _g(m: Any, k: str) -> Any:
    try:
        return m[k]
    except (KeyError, IndexError, TypeError):
        return None


def surface_distance_m(lat1: float, lon1: float, lat2: float, lon2: float,
                       radius_m: float) -> float:
    """Great-circle distance in metres between two points on a body."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing 0..360 (0 = north), as the game's Heading counts it."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def relative_deg(bearing: float, heading: float) -> float:
    """-180..180: negative = turn left."""
    return (bearing - heading + 540.0) % 360.0 - 180.0


def direction_text(bearing: float, heading: Optional[float]) -> str:
    """ASCII arrow - overlay fonts differ, plain characters always render."""
    if heading is None:
        return "brg %03d" % round(bearing)
    rel = relative_deg(bearing, float(heading))
    a = abs(rel)
    if a <= 8:
        return "^ ahead"
    if a >= 165:
        return "v behind"
    n = "%d" % round(a)
    if rel < 0:
        return ("<< " if a > 90 else "< ") + n
    return n + (" >>" if a > 90 else " >")


def course_text(bearing: float, heading: Optional[float]) -> str:
    """Absolute course to the point ("brg 255", 0 = north, as the game's
    compass counts it) and, with a heading, the turn to it: "brg 255 < 30"."""
    brg = "brg %03d" % (round(bearing) % 360)
    if heading is None:
        return brg
    return "%s %s" % (brg, direction_text(bearing, heading))


def fmt_dist(m: float) -> str:
    """A distance for the overlay: metres, then km with one decimal, then whole
    km."""
    if m < 1000:
        return "%d m" % round(m)
    if m < 100000:
        return "%.1f km" % (m / 1000.0)
    return "%d km" % round(m / 1000.0)


def body_state(marks: Iterable[Any], radius: Optional[float] = None) -> Dict[str, Any]:
    """
    Replay the marks of one body in time order.

    parked   the SRV left standing (Disembark from the SRV, not yet re-entered)
    ship     the ship standing on the ground (Touchdown by the ship, not yet
             lifted off or dismissed); a recalled ship that lands writes a
             Touchdown of its own (PlayerControlled false). The Nomad gives
             no such point - the ship follows it at some 2-3 km - and a drop
             from a landed ship keeps the Touchdown.
    ship_away  4.12: the ship has flown off and must be recalled - {"ts",
             "why"}: "hover" when an SRV was dropped from a hovering ship
             (it leaves at once and the journal writes nothing for that -
             developer's journals of 14.11.2026), "dismissed" for a Liftoff
             without the player (sent away, or it left on its own). Over
             when you are back aboard (DockSRV, Embark) or it lands again.
    species  one entry per species: samples taken since its last Log (the
             game restarts the count on a new Log), positions, analysed
    sites    positioned finds worth returning to, close ones merged
    rigs     Rhino mining rigs, where they were collected (driving over a
             folded rig writes one MiningRefined per tonne; placing one
             writes nothing): n = 1, 2 ... per Rhino launch, tonnes, type.
             Tonnes more than RIG_GAP_S apart, or (with the body radius)
             more than RIG_SPREAD_M apart, are another rig.
    """
    r = _BodyReplay(radius)
    for m in sorted(marks, key=lambda r: _g(r, "ts") or ""):
        r.feed(m)
    return {"parked": r.parked, "ship": r.ship, "ship_away": r.ship_away,
            "species": list(r.species.values()), "sites": r.sites, "rigs": r.rigs}


class _BodyReplay:
    """body_state's replay: the marks of one body fed in time order."""

    def __init__(self, radius: Optional[float]) -> None:
        self.radius = radius
        self.parked: Any = None
        self.ship: Any = None
        self.ship_away: Optional[Dict[str, Any]] = None
        self.rigs: List[Dict[str, Any]] = []
        self.outing = 0
        self.species: Dict[str, Dict[str, Any]] = {}
        self.sites: List[Dict[str, Any]] = []

    def feed(self, m: Any) -> None:
        """One mark."""
        kind = _g(m, "kind") or ""
        lat, lon = _g(m, "lat"), _g(m, "lon")
        detail = _g(m, "detail")
        self._vehicles(m, kind, lat, lon, detail)
        if kind == "srv_in" or (kind == "embark" and _g(m, "label") != "SRV"):
            self.ship_away = None        # back on board: the ship is here
        elif kind.startswith("bio_"):
            self._bio(m, kind, lat, lon, detail)
        if kind in SITE_KINDS and lat is not None:
            self.sites.append({"kind": kind, "label": _g(m, "label") or kind,
                               "detail": detail, "lat": float(lat), "lon": float(lon),
                               "ts": _g(m, "ts")})

    def _vehicles(self, m: Any, kind: str, lat: Any, lon: Any, detail: Any) -> None:
        """Parked SRV, ship on the ground or hovering, mining rigs."""
        if kind == "srv_parked":
            self.parked = m if lat is not None else self.parked
        elif kind == "srv_in" or (kind == "embark" and _g(m, "label") == "SRV"):
            self.parked = None
        elif kind == "touchdown" and detail != "srv":
            self.ship = m if lat is not None else self.ship
            self.ship_away = None        # landed - by you, or recalled
        elif kind == "liftoff" and detail != "srv":
            self.ship = None
            # without the player: sent away or left on its own - recall it
            self.ship_away = {"ts": _g(m, "ts"), "why": "dismissed"} if detail == "auto" else None
        elif kind == "refined" and lat is not None:
            self._rig(m, lat, lon)
        elif kind == "srv_out":
            self._srv_out(m, lat, lon)

    def _rig(self, m: Any, lat: Any, lon: Any) -> None:
        """One refined tonne: the same rig, or a new one."""
        rigs, outing, radius = self.rigs, self.outing, self.radius
        t = _ts(_g(m, "ts"))
        last = rigs[-1] if rigs else None
        same = (last is not None and last["outing"] == outing
                and t - last["last_t"] <= RIG_GAP_S
                and (not radius or surface_distance_m(last["lat"], last["lon"], float(lat),
                                                      float(lon), radius) <= RIG_SPREAD_M))
        if same:
            last["tonnes"] += 1
            last["last_t"] = t
        else:
            n = sum(1 for r in rigs if r["outing"] == outing) + 1
            rigs.append({"n": n, "outing": outing, "lat": float(lat), "lon": float(lon),
                         "ts": _g(m, "ts"), "last_t": t, "tonnes": 1,
                         "type": (_g(m, "label") or "?").split("#")[0]})

    def _srv_out(self, m: Any, lat: Any, lon: Any) -> None:
        """A vehicle launched: a new Rhino outing; the ship flying along (Nomad),
        or - dropped from a hover - flown off until recalled."""
        vehicle = (_g(m, "label") or "").lower()
        if "rhino" in vehicle:
            self.outing += 1
        if "nomad" in vehicle:
            self.ship = None             # the ship flies along with the Nomad
        elif self.ship is None:
            # no Touchdown before: dropped from a hovering ship, which leaves
            # at once - nothing in the journal says so (14.11.2026)
            self.ship_away = {"ts": _g(m, "ts"), "why": "hover"}

    def _bio(self, m: Any, kind: str, lat: Any, lon: Any, detail: Any) -> None:
        """A bio log, sample or analysis of one species."""
        name = _g(m, "label") or "?"
        s = self.species.get(name)
        if kind == "bio_log" or s is None:
            s = self.species[name] = {"species": name, "genus": detail, "samples": 0,
                                      "points": [], "analysed": False, "last": None}
        if kind in ("bio_log", "bio_sample"):
            s["samples"] = min(3, s["samples"] + 1)
            if lat is not None:
                s["points"].append((float(lat), float(lon)))
            s["last"] = _g(m, "ts")
        elif kind == "bio_analyse":
            s["analysed"] = True
            s["samples"] = 3


RIG_GAP_S = 8.0       # one rig's tonnes come 1-2 s apart (11 t in some 13 s)
RIG_SPREAD_M = 25.0   # rigs stand well apart (seen: 76 m); driving over one is metres


def _ts(stamp: Any) -> float:
    """Journal timestamp to seconds; plain numbers pass (tests)."""
    try:
        return float(calendar.timegm(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        try:
            return float(stamp)
        except (ValueError, TypeError):
            return 0.0


def _merge_sites(sites: List[Dict[str, Any]], radius: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in sites:
        if any(o["label"] == s["label"] and
               surface_distance_m(o["lat"], o["lon"], s["lat"], s["lon"], radius) < SITE_MERGE_M
               for o in out):
            continue
        out.append(s)
    return out


def bio_summary(state: Dict[str, Any], sig_bio: Optional[int],
                genera: Sequence[str]) -> Dict[str, Any]:
    """Analysed species, genera still open (the DSS named them, none analysed)."""
    sp = state["species"]
    done_genera = {s["genus"] for s in sp if s["analysed"] and s["genus"]}
    started = {s["genus"] for s in sp if s["genus"]}
    return {"analysed": sum(1 for s in sp if s["analysed"]),
            "in_progress": [s for s in sp if not s["analysed"]],
            "open_genera": [g for g in genera if g not in done_genera and g not in started],
            "signals": sig_bio}


LINE_MAX = 44          # characters per overlay line (the block may stand at x = 900 of 1280)


def head_line(label: str, done: int, open_n: int = 0, lost_n: int = 0,
              to_find: Sequence[str] = (), signals: Optional[int] = None) -> str:
    """
    The head of the NAV / KNOWN POINTS block, never longer than LINE_MAX:
    "KNOWN POINTS  bio 1 done, 1 open, 2 lost - redo | to find: Bacterium".
    What gives way first: the signal count, then genera still to find (named
    while they fit, the rest as "+n"), then " - redo".
    """
    core = "bio %d done" % done + (", %d open" % open_n if open_n else "")
    base = ""
    for redo in (True, False):
        lost = (", %d lost%s" % (lost_n, " - redo" if redo else "")) if lost_n else ""
        base = "%s  %s%s" % (label, core, lost)
        if len(base) <= LINE_MAX:
            break
    if len(base) > LINE_MAX:
        return base[:LINE_MAX]
    if to_find:
        names: List[str] = []
        for i, g in enumerate(to_find):
            more = len(to_find) - i - 1
            t = base + " | to find: " + ", ".join(names + [g]) + (" +%d" % more if more else "")
            if len(t) > LINE_MAX:
                break
            names.append(g)
        if names:
            more = len(to_find) - len(names)
            return base + " | to find: " + ", ".join(names) + (" +%d" % more if more else "")
        t = base + " | %d to find" % len(to_find)
        return t if len(t) <= LINE_MAX else base
    if signals:
        t = base + " | %d signal%s" % (signals, "" if signals == 1 else "s")
        return t if len(t) <= LINE_MAX else base
    return base


def away_line(away: Dict[str, Any], now: Optional[float], colour: str) -> Line:
    """4.12: the ship has flown off - no point to steer to, a recall to make."""
    t0 = _ts(away.get("ts"))
    mins = int((now - t0) // 60) if now is not None and t0 > 1e9 and now >= t0 else None
    since = (" %d min" % mins) if mins is not None else ""
    why = "dismissed" if away.get("why") == "dismissed" else "flew off"
    return ("%-19s %s" % ("SHIP AWAY%s" % since, "%s - recall it" % why), colour)


def compass_lines(pos: Dict[str, Any], marks: Iterable[Any], radius: float,
                  sig_bio: Optional[int] = None, genera: Sequence[str] = (),
                  colours: Optional[Dict[str, str]] = None, limit: int = 6,
                  orbit: bool = False, lost: Sequence[str] = (),
                  now: Optional[float] = None) -> List[Line]:
    """
    The NAV block: one line per point, nearest first within its group -
    parked SRV, parked ship, unfinished species, species lost in a crash,
    sites. Each with the distance, the absolute course and the turn to it.
    Empty when the body holds nothing to point at.

    lost  what of this body went down with the ship and is not redone yet
          (cmdr_bodies.lost_what: "scan", "map", "bio:<species>"). A lost
          species is not "done" - it counts as "lost - redo" and points to
          where it was sampled, until a new analysis clears the mark.
    """
    col = colours or {}
    c_head, c_data = col.get("head", "#3EF2E0"), col.get("data", "#7CFF6B")
    c_warn, c_dim, c_new = col.get("warn", "#FFB23E"), col.get("dim", "#8FA3A6"), \
        col.get("new", "#B57CFF")
    if radius <= 0 or pos.get("lat") is None:
        return []
    lat, lon, hdg = float(pos["lat"]), float(pos["lon"]), pos.get("heading")
    st = body_state(marks)
    summ = bio_summary(st, sig_bio, genera)

    def entry(label: str, plat: float, plon: float, colour: str) -> Tuple[float, Line]:
        d = surface_distance_m(lat, lon, plat, plon, radius)
        b = bearing_deg(lat, lon, plat, plon)
        # 19 + 1 + 7 + 1 + 16 = 44 characters, like the other overlay blocks
        return d, ("%-19s %7s %s" % (label[:19], fmt_dist(d), course_text(b, hdg)), colour)

    rows: List[Line] = []
    if st["parked"] is not None:
        p = st["parked"]
        rows.append(entry("%s PARKED" % (_g(p, "detail") or "SRV").upper(),
                          float(p["lat"]), float(p["lon"]), c_warn)[1])
    if st["ship"] is not None:
        p = st["ship"]
        rows.append(entry("SHIP", float(p["lat"]), float(p["lon"]), c_warn)[1])
    elif st["ship_away"] is not None and pos.get("mode") != "ship":     # aboard: it is here
        rows.append(away_line(st["ship_away"], now, c_warn))
    bio = []
    for s in summ["in_progress"]:
        if s["points"]:
            plat, plon = s["points"][-1]
            bio.append(entry("%s %d/3" % (s["species"][:15], s["samples"]), plat, plon, c_new))
    rows += [l for _d, l in sorted(bio, key=lambda t: t[0])]
    # lost in a crash and not started again: back to where it was sampled
    busy = {s["species"] for s in summ["in_progress"]}
    lost_sp = {w[4:] for w in lost if isinstance(w, str) and w.startswith("bio:")} - busy
    gone = []
    for s in st["species"]:
        if s["species"] in lost_sp and s["points"]:
            plat, plon = s["points"][-1]
            gone.append(entry("%s LOST" % s["species"][:14], plat, plon, c_warn))
    rows += [l for _d, l in sorted(gone, key=lambda t: t[0])]
    # a codex entry of a species still being sampled is the same point as
    # its sample line; one of an analysed species stays (Brain Trees are
    # worth coming back to for their materials) but steps back in colour
    done = {s["species"] for s in st["species"] if s["analysed"]} - lost_sp
    sites = [entry(s["label"], s["lat"], s["lon"],
                   c_dim if s["kind"] == "screenshot" or s["label"] in done else c_data)
             for s in _merge_sites(st["sites"], radius) if s["label"] not in busy]
    rows += [l for _d, l in sorted(sites, key=lambda t: t[0])]

    if not rows and not summ["open_genera"] and not lost_sp:
        return []
    label = "KNOWN POINTS" if orbit else "NAV"
    if summ["analysed"] or summ["in_progress"] or sig_bio or lost_sp:
        # species, not signals: one Brain Trees signal holds several species
        head = head_line(label, len(done), len(summ["in_progress"]), len(lost_sp),
                         summ["open_genera"], sig_bio if sig_bio and not genera else None)
    else:
        head = label
    out: List[Line] = [(head, c_head)]
    out += rows[:limit]
    if len(rows) > limit:
        out.append(("+%d more" % (len(rows) - limit), c_dim))
    return out
