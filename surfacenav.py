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
             lifted off or dismissed) - or, with "hover": True, hovering
             where it dropped the Rhino: the Rhino is launched from a ship
             that hovers just above the ground and stays there without a
             Touchdown. The Nomad gives no such point - the ship follows it
             at some 2-3 km - and a drop from a landed ship keeps the
             Touchdown. Last known only: sending a hovering ship away
             writes nothing.
    species  one entry per species: samples taken since its last Log (the
             game restarts the count on a new Log), positions, analysed
    sites    positioned finds worth returning to, close ones merged
    rigs     Rhino mining rigs, where they were collected (driving over a
             folded rig writes one MiningRefined per tonne; placing one
             writes nothing): n = 1, 2 ... per Rhino launch, tonnes, type.
             Tonnes more than RIG_GAP_S apart, or (with the body radius)
             more than RIG_SPREAD_M apart, are another rig.
    """
    parked = ship = None
    rigs: List[Dict[str, Any]] = []
    outing = 0
    species: Dict[str, Dict[str, Any]] = {}
    sites: List[Dict[str, Any]] = []
    for m in sorted(marks, key=lambda r: _g(r, "ts") or ""):
        kind = _g(m, "kind") or ""
        lat, lon = _g(m, "lat"), _g(m, "lon")
        detail = _g(m, "detail")
        if kind == "srv_parked":
            parked = m if lat is not None else parked
        elif kind == "srv_in" or (kind == "embark" and _g(m, "label") == "SRV"):
            parked = None
        elif kind == "touchdown" and detail != "srv":
            ship = m if lat is not None else ship
        elif kind == "liftoff" and detail != "srv":
            ship = None
        elif kind == "refined" and lat is not None:
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
        elif kind == "srv_out":
            vehicle = (_g(m, "label") or "").lower()
            if "rhino" in vehicle:
                outing += 1
            if "nomad" in vehicle:
                ship = None              # the ship flies along with the Nomad
            elif "rhino" in vehicle and ship is None and lat is not None:
                ship = {"ts": _g(m, "ts"), "kind": "srv_out", "label": _g(m, "label"),
                        "detail": "hover", "lat": lat, "lon": lon, "hover": True}
        back_aboard = kind == "srv_in" or (kind == "embark" and _g(m, "label") != "SRV")
        if back_aboard and isinstance(ship, dict) and ship.get("hover"):
            ship = None                  # back on board the hovering ship
        elif kind.startswith("bio_"):
            name = _g(m, "label") or "?"
            s = species.get(name)
            if kind == "bio_log" or s is None:
                s = species[name] = {"species": name, "genus": detail, "samples": 0,
                                     "points": [], "analysed": False, "last": None}
            if kind in ("bio_log", "bio_sample"):
                s["samples"] = min(3, s["samples"] + 1)
                if lat is not None:
                    s["points"].append((float(lat), float(lon)))
                s["last"] = _g(m, "ts")
            elif kind == "bio_analyse":
                s["analysed"] = True
                s["samples"] = 3
        if kind in SITE_KINDS and lat is not None:
            sites.append({"kind": kind, "label": _g(m, "label") or kind,
                          "detail": detail, "lat": float(lat), "lon": float(lon),
                          "ts": _g(m, "ts")})
    return {"parked": parked, "ship": ship, "species": list(species.values()),
            "sites": sites, "rigs": rigs}


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


def compass_lines(pos: Dict[str, Any], marks: Iterable[Any], radius: float,
                  sig_bio: Optional[int] = None, genera: Sequence[str] = (),
                  colours: Optional[Dict[str, str]] = None, limit: int = 6,
                  orbit: bool = False, lost: Sequence[str] = ()) -> List[Line]:
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
        hover = isinstance(p, dict) and p.get("hover")
        rows.append(entry("SHIP (hover)" if hover else "SHIP", float(p["lat"]),
                          float(p["lon"]), c_warn)[1])
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

    bio_txt = ""
    if summ["analysed"] or summ["in_progress"] or sig_bio or lost_sp:
        # species, not signals: one Brain Trees signal holds several species
        bio_txt = "bio %d done" % len(done)
        if summ["in_progress"]:
            bio_txt += ", %d open" % len(summ["in_progress"])
        if lost_sp:
            bio_txt += ", %d lost - redo" % len(lost_sp)
        if summ["open_genera"]:
            bio_txt += " | not found: " + ", ".join(summ["open_genera"])[:40]
        elif sig_bio and not genera:
            bio_txt += " | %d signal%s" % (sig_bio, "" if sig_bio == 1 else "s")
    if not rows and not summ["open_genera"] and not lost_sp:
        return []
    head = "%s  %s" % ("KNOWN POINTS" if orbit else "NAV", bio_txt)
    out: List[Line] = [(head.rstrip(), c_head)]
    out += rows[:limit]
    if len(rows) > limit:
        out.append(("+%d more" % (len(rows) - limit), c_dim))
    return out


def _selftest() -> None:
    assert round(bearing_deg(0, 0, 1, 0)) == 0
    assert round(bearing_deg(0, 0, 0, 1)) == 90
    assert direction_text(90, 90) == "^ ahead"
    assert direction_text(60, 90) == "< 30"
    assert direction_text(200, 90) == "110 >>"
    assert direction_text(275, 90) == "v behind"
    assert course_text(255.4, None) == "brg 255"
    assert course_text(255.0, 285.0) == "brg 255 < 30", course_text(255.0, 285.0)
    assert course_text(359.7, 0.0) == "brg 000 ^ ahead", course_text(359.7, 0.0)
    assert course_text(7.0, 0.0) == "brg 007 ^ ahead"
    marks = [
        {"ts": "1", "kind": "touchdown", "label": "b", "detail": "srv", "lat": 0.0, "lon": 0.0},
        {"ts": "2", "kind": "srv_parked", "label": "SRV", "detail": "Nomad", "lat": 0.0, "lon": 0.0},
        {"ts": "3", "kind": "bio_log", "label": "Roseum Brain Tree", "detail": "Brain Trees",
         "lat": 0.001, "lon": 0.0},
        {"ts": "3", "kind": "codex", "label": "Roseum Brain Tree", "detail": "Organic structures",
         "lat": 0.001, "lon": 0.0},
        {"ts": "4", "kind": "bio_sample", "label": "Roseum Brain Tree", "detail": "Brain Trees",
         "lat": 0.002, "lon": 0.0},
    ]
    st = body_state(marks)
    assert st["ship"] is None and st["parked"]["detail"] == "Nomad"
    assert st["species"][0]["samples"] == 2 and not st["species"][0]["analysed"]
    lines = compass_lines({"lat": 0.0, "lon": 0.001, "heading": 0}, marks, 400000.0,
                          sig_bio=2, genera=["Brain Trees", "Bacterium"])
    assert lines[1][0].startswith("NOMAD PARKED"), lines
    assert "not found: Bacterium" in lines[0][0], lines
    assert not any(l[0].startswith("Roseum Brain Tree ") and "/3" not in l[0]
                   for l in lines), lines
    # every point names its absolute course next to the turn
    assert all(" brg " in l[0] for l in lines[1:]), lines
    assert all(len(l[0]) <= 44 for l in lines[1:]), lines   # the points; the head may run on
    assert len(compass_lines({"lat": 0.0, "lon": 0.0, "heading": 0.0}, [
        {"ts": "1", "kind": "codex", "label": "Very long find name of a site", "detail": None,
         "lat": 0.0, "lon": -1.0}], 400000.0)[1][0]) <= 44
    nomad = lines[1][0]
    assert nomad.endswith("brg 270 < 90"), nomad
    # lost in a crash (screenshot 12.11.: "bio 2 done" for two lost species)
    lm = [
        {"ts": "1", "kind": "bio_log", "label": "Stratum Tectonicas", "detail": "Stratum",
         "lat": 0.0, "lon": 0.01},
        {"ts": "2", "kind": "bio_analyse", "label": "Stratum Tectonicas", "detail": "Stratum",
         "lat": 0.0, "lon": 0.01},
        {"ts": "3", "kind": "bio_log", "label": "Bacterium Cerbrus", "detail": "Bacterium",
         "lat": 0.01, "lon": 0.0},
        {"ts": "4", "kind": "bio_analyse", "label": "Bacterium Cerbrus", "detail": "Bacterium",
         "lat": 0.01, "lon": 0.0},
        {"ts": "5", "kind": "codex", "label": "Crystalline Shards", "detail": "Shards",
         "lat": -0.01, "lon": 0.0},
    ]
    here = {"lat": 0.0, "lon": 0.0, "heading": 90}
    ok = compass_lines(here, lm, 400000.0, sig_bio=2, orbit=True)
    assert ok[0][0].startswith("KNOWN POINTS  bio 2 done"), ok
    lost = ["map", "bio:Stratum Tectonicas", "bio:Bacterium Cerbrus"]
    bad = compass_lines(here, lm, 400000.0, sig_bio=2, orbit=True, lost=lost)
    assert bad[0][0].startswith("KNOWN POINTS  bio 0 done, 2 lost - redo"), bad
    st_row = [l for l in bad if l[0].startswith("Stratum Tecton LOST")]
    assert st_row and "brg 090 ^ ahead" in st_row[0][0], bad
    assert st_row[0][1] == "#FFB23E", st_row
    # one redo started: that species is open again (n/3), the other still lost
    lm.append({"ts": "6", "kind": "bio_log", "label": "Stratum Tectonicas",
               "detail": "Stratum", "lat": 0.0, "lon": 0.02})
    redo = compass_lines(here, lm, 400000.0, sig_bio=2, orbit=True, lost=lost)
    assert redo[0][0].startswith("KNOWN POINTS  bio 0 done, 1 open, 1 lost - redo"), redo
    assert any(l[0].startswith("Stratum Tectoni 1/3") for l in redo), redo
    # a lost species without any position still shows in the head
    assert compass_lines(here, [], 400000.0, lost=["bio:Aleoida Gravis"])[0][0] \
        == "NAV  bio 0 done, 1 lost - redo"
    marks.append({"ts": "5", "kind": "embark", "label": "SRV", "detail": None,
                  "lat": 0.0, "lon": 0.0})
    assert body_state(marks)["parked"] is None
    # a new Log restarts the count
    marks.append({"ts": "6", "kind": "bio_log", "label": "Roseum Brain Tree",
                  "detail": "Brain Trees", "lat": 0.01, "lon": 0.0})
    assert body_state(marks)["species"][0]["samples"] == 1
    # the Rhino: dropped from a hovering ship - no Touchdown, the ship stays
    rh = [{"ts": "1", "kind": "srv_out", "label": "SRV Rhino", "detail": None,
           "lat": -26.05, "lon": 143.60}]
    s = body_state(rh)["ship"]
    assert s and s["hover"] and s["lat"] == -26.05, s
    lines = compass_lines({"lat": -26.06, "lon": 143.61, "heading": 0}, rh, 492617.0)
    assert any(l[0].startswith("SHIP (hover)") for l in lines), lines
    assert body_state(rh + [{"ts": "2", "kind": "srv_in", "label": "SRV Rhino",
                             "detail": None, "lat": 0.0, "lon": 0.0}])["ship"] is None
    # on foot from the Rhino and back into it: the ship still hovers
    foot = rh + [{"ts": "2", "kind": "srv_parked", "label": "SRV", "detail": "SRV Rhino",
                  "lat": -26.0, "lon": 143.7},
                 {"ts": "3", "kind": "embark", "label": "SRV", "detail": None,
                  "lat": -26.0, "lon": 143.7}]
    assert body_state(foot)["ship"]["hover"]
    # a Rhino out of a landed ship: the Touchdown stays the ship's point
    td = [{"ts": "0", "kind": "touchdown", "label": "b", "detail": "ship", "lat": 1.0, "lon": 2.0}]
    s = body_state(td + rh)["ship"]
    assert s["kind"] == "touchdown" and not (isinstance(s, dict) and s.get("hover")), s
    # the Nomad: the ship flies along - no point to show
    assert body_state([{"ts": "1", "kind": "srv_out", "label": "Nomad", "detail": None,
                        "lat": 1.0, "lon": 1.0}])["ship"] is None
    # sent away / recalled: Liftoff or Touchdown without the player win
    assert body_state(rh + [{"ts": "2", "kind": "liftoff", "label": "b", "detail": "auto",
                             "lat": -26.05, "lon": 143.60}])["ship"] is None
    s = body_state(rh + [{"ts": "2", "kind": "touchdown", "label": "b", "detail": "auto",
                          "lat": -26.2, "lon": 143.7}])["ship"]
    assert s["lat"] == -26.2 and s["kind"] == "touchdown", s
    # Rhino rigs: tonnes close in time and place are one rig; numbered per launch
    def iso(sec):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1794330000 + sec))

    def ref(sec, lat, lon, label="Deuterium"):
        return {"ts": iso(sec), "kind": "refined", "label": label, "detail": "rig",
                "lat": lat, "lon": lon}

    rr = [{"ts": iso(10), "kind": "srv_out", "label": "SRV Rhino", "lat": 0.0, "lon": 0.0}]
    rr += [ref(100 + i, 0.0, 0.0001) for i in range(11)]
    rr.append(ref(105, 0.0, 0.0001, "Deuterium#1"))       # two in the same second
    rr += [ref(300 + i, 0.0005, 0.0008) for i in range(11)]
    rr.append(ref(312, 0.01, 0.0))                          # 2 s later but 4 km off
    rigs = body_state(rr, 492617.0)["rigs"]
    got = [(r["n"], r["tonnes"], r["type"]) for r in rigs]
    assert got == [(1, 12, "Deuterium"), (2, 11, "Deuterium"), (3, 1, "Deuterium")], got
    # without the radius only time splits
    assert [r["tonnes"] for r in body_state(rr)["rigs"]] == [12, 12]
    rr.append({"ts": iso(900), "kind": "srv_out", "label": "SRV Rhino", "lat": 0.0, "lon": 0.0})
    rr.append(ref(1000, 0.02, 0.0, "Gold"))
    last = body_state(rr, 492617.0)["rigs"][-1]
    assert (last["n"], last["type"], last["outing"]) == (1, "Gold", 2), last
    print("surfacenav selftest ok")


if __name__ == "__main__":
    _selftest()
