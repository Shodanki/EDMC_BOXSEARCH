# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
STATISTICS: the game's own record of the commander - the Statistics event
written at every login - with ranks (Rank / Progress), reputation, and how
much each number grew over a chosen period (the Statistics event from back
then against the latest one).

Reads the journal only.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import fleet as fl
from .live import parse_ts

# the game's rank titles (proper names - shown as the game shows them in English)
_ELITE = ["Elite", "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V"]
RANKS = {
    "Combat": ["Harmless", "Mostly Harmless", "Novice", "Competent", "Expert", "Master", "Dangerous",
               "Deadly"] + _ELITE,
    "Trade": ["Penniless", "Mostly Penniless", "Peddler", "Dealer", "Merchant", "Broker", "Entrepreneur",
              "Tycoon"] + _ELITE,
    "Explore": ["Aimless", "Mostly Aimless", "Scout", "Surveyor", "Trailblazer", "Pathfinder", "Ranger",
                "Pioneer"] + _ELITE,
    "Exobiologist": ["Directionless", "Mostly Directionless", "Compiler", "Collector", "Cataloguer",
                     "Taxonomist", "Ecologist", "Geneticist"] + _ELITE,
    "Soldier": ["Defenceless", "Mostly Defenceless", "Rookie", "Soldier", "Gunslinger", "Warrior",
                "Gladiator", "Deadeye"] + _ELITE,
    "CQC": ["Helpless", "Mostly Helpless", "Amateur", "Semi Professional", "Professional", "Champion",
            "Hero", "Legend"] + _ELITE,
    "Empire": ["None", "Outsider", "Serf", "Master", "Squire", "Knight", "Lord", "Baron", "Viscount",
               "Count", "Earl", "Marquis", "Duke", "Prince", "King"],
    "Federation": ["None", "Recruit", "Cadet", "Midshipman", "Petty Officer", "Chief Petty Officer",
                   "Warrant Officer", "Ensign", "Lieutenant", "Lieutenant Commander", "Post Commander",
                   "Post Captain", "Rear Admiral", "Vice Admiral", "Admiral"],
}
RANK_ORDER = ["Explore", "Exobiologist", "Trade", "Combat", "Soldier", "CQC", "Empire", "Federation"]

# the sections the view shows (the event has more: squadron, multicrew ...)
SECTIONS = ("Exploration", "Exobiology", "Mining", "FLEETCARRIER", "Bank_Account", "Trading", "Combat",
            "Search_And_Rescue", "Passengers", "Crafting", "Material_Trader_Stats", "Crime", "Crew",
            "Smuggling")


# ST1 (5.0): the numbers drawn over time - one value per UTC day (the last
# login of the day), from the Statistics events of the period
SERIES = (("Exploration", "Systems_Visited"), ("Exploration", "Exploration_Profits"),
          ("Exploration", "Planets_Scanned_To_Level_3"), ("Exobiology", "Organic_Data_Profits"),
          ("Mining", "Quantity_Mined"), ("Bank_Account", "Current_Wealth"))
DSS_GAP_S = 15 * 60      # two maps in one system further apart than this: not one stretch of work


def series(stats: List[Dict[str, Any]], since: Optional[float]) -> Dict[str, List[List[float]]]:
    """ST1: "Section.Key" -> [[day start (unix), value], ...] from `since` on,
    the last Statistics event of each UTC day."""
    by_day: Dict[int, Dict[str, Any]] = {}
    for e in stats:
        t = parse_ts(e.get("timestamp"))
        if t is None or (since is not None and t < since):
            continue
        by_day[int(t // 86400)] = e
    out: Dict[str, List[List[float]]] = {}
    for sec, key in SERIES:
        pts = [[day * 86400, (e.get(sec) or {}).get(key)] for day, e in sorted(by_day.items())]
        pts = [p for p in pts if isinstance(p[1], (int, float)) and not isinstance(p[1], bool)]
        if len(pts) >= 2:
            out[sec + "." + key] = pts
    return out


def first_discoveries(evs: List[Dict[str, Any]], months: int = 12) -> List[Dict[str, Any]]:
    """ST1: per calendar month (UTC) the bodies you scanned yourself (no nav
    beacon) and how many of them nobody had discovered before
    (WasDiscovered false) - each body once, at its first scan; the newest
    `months` months that have scans."""
    seen = set()
    by: Dict[str, List[int]] = {}
    for e in evs:
        if e.get("event") != "Scan" or e.get("ScanType") == "NavBeaconDetail" or "WasDiscovered" not in e:
            continue
        key = (e.get("SystemAddress"), e.get("BodyID") if e.get("BodyID") is not None else e.get("BodyName"))
        t = parse_ts(e.get("timestamp"))
        if key in seen or t is None:
            continue
        seen.add(key)
        m = time.strftime("%Y-%m", time.gmtime(t))
        row = by.setdefault(m, [0, 0])
        row[0] += 1
        row[1] += 1 if e.get("WasDiscovered") is False else 0
    return [{"month": m, "scanned": v[0], "first": v[1], "pct": round(100.0 * v[1] / v[0], 1)}
            for m, v in sorted(by.items())[-months:]]


def dss_tiles(evs: List[Dict[str, Any]], since: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """
    ST1: the detailed surface scans of the period - how many, how many
    efficient (probes within the target), probes per map (median), and the
    time per map: the gap between two maps in one system when it is under
    DSS_GAP_S (flight and mapping together) - median, quartiles and n.
    """
    maps = [e for e in evs if e.get("event") == "SAAScanComplete"
            and (since is None or (parse_ts(e.get("timestamp")) or 0) >= since)]
    if not maps:
        return None
    eff = [e for e in maps if e.get("ProbesUsed") is not None and e.get("EfficiencyTarget") is not None]
    good = sum(1 for e in eff if e["ProbesUsed"] <= e["EfficiencyTarget"])
    probes = sorted(e["ProbesUsed"] for e in eff)
    gaps: List[float] = []
    prev: Dict[Any, float] = {}
    for e in maps:
        t = parse_ts(e.get("timestamp"))
        a = e.get("SystemAddress")
        if t is None:
            continue
        if a in prev and 0 < t - prev[a] < DSS_GAP_S:
            gaps.append(t - prev[a])
        prev[a] = t
    gaps.sort()
    q = (lambda xs, f: xs[min(len(xs) - 1, int(f * len(xs)))]) if gaps else None
    return {"maps": len(maps), "rated": len(eff), "efficient": good,
            "efficient_pct": round(100.0 * good / len(eff), 1) if eff else None,
            "probes_median": probes[len(probes) // 2] if probes else None,
            "gap_n": len(gaps), "gap_median_s": round(q(gaps, 0.5)) if q else None,
            "gap_q1_s": round(q(gaps, 0.25)) if q else None, "gap_q3_s": round(q(gaps, 0.75)) if q else None}


SESSION_GAP_S = 30 * 60     # RT1: no event for this long ends a session
SESSION_MIN_S = 30 * 60     # ... and only sessions this long go into the medians


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0)


class _Session:
    """One game session of play_sessions: time, jumps, bodies, value."""

    def __init__(self, t: float) -> None:
        self.start = self.end = t
        self.jumps = 0
        self.bodies: Dict[Any, Dict[str, Any]] = {}
        self.explo = 0.0
        self.bio = 0.0

    def out(self) -> Dict[str, Any]:
        """The session as the view shows it, with systems and value per hour."""
        h = max(1e-9, (self.end - self.start) / 3600.0)
        value = self.explo + self.bio
        return {"start": self.start, "minutes": round((self.end - self.start) / 60.0), "jumps": self.jumps,
                "bodies": len(self.bodies), "explo": int(self.explo), "bio": int(self.bio),
                "jumps_h": round(self.jumps / h, 1), "value_h": int(value / h)}


def play_sessions(evs: List[Dict[str, Any]], body_value: Any = None,
                  bio_values: Optional[Dict[str, Dict[str, int]]] = None, keep: int = 12) -> Dict[str, Any]:
    """
    RT1 (5.0): systems and value per hour, per game session - a LoadGame,
    or a pause of SESSION_GAP_S, starts a new one. Value is what you
    gathered, not what you sold: the bodyvalue estimate of the bodies you
    scanned first in it (mapped ones at their mapped value) plus your own
    prices of the species you analysed (unsold.BONUS_FACTOR left out) - so
    "~". Medians over the sessions of at least SESSION_MIN_S.
    """
    from .unsold import _row_values, _scan_row
    seen: set = set()
    cur: Optional[_Session] = None
    done: List[_Session] = []
    for e in evs:
        t = parse_ts(e.get("timestamp"))
        if t is None:
            continue
        if cur is None or e.get("event") == "LoadGame" or t - cur.end > SESSION_GAP_S:
            if cur is not None:
                done.append(cur)
            cur = _Session(t)
        cur.end = t
        _session_event(cur, e, seen, body_value, bio_values or {}, _row_values, _scan_row)
    if cur is not None:
        done.append(cur)
    rows = [s.out() for s in done if s.jumps or s.bodies or s.bio]
    long_ = [r for r in rows if r["minutes"] * 60 >= SESSION_MIN_S]
    return {"sessions": list(reversed(rows[-keep:])), "n": len(long_),
            "jumps_h": _median([r["jumps_h"] for r in long_]), "value_h": _median([r["value_h"] for r in long_]),
            "valued": body_value is not None}


def _session_event(cur: "_Session", e: Dict[str, Any], seen: set, bv: Any, bio_values: Dict[str, Dict[str, int]],
                   row_values: Any, scan_row: Any) -> None:
    """One event into a session: a jump, a first scan, a map, an analysis."""
    ev = e.get("event")
    if ev == "FSDJump":
        cur.jumps += 1
    elif ev == "Scan" and e.get("ScanType") != "NavBeaconDetail" and bv is not None:
        key = (e.get("SystemAddress"), e.get("BodyID"))
        if key not in seen:
            seen.add(key)
            r = scan_row(e)
            cur.bodies[key] = r
            cur.explo += row_values(bv, r)[0]
    elif ev == "SAAScanComplete" and bv is not None:
        r = cur.bodies.get((e.get("SystemAddress"), e.get("BodyID")))
        if r is not None:
            scan, full = row_values(bv, r)
            cur.explo += full - scan
    elif ev == "ScanOrganic" and e.get("ScanType") == "Analyse":
        v = bio_values.get(e.get("Species_Localised") or e.get("Species") or "")
        cur.bio += (v or {}).get("value") or 0


def rank_name(kind: str, n: Optional[int]) -> Optional[str]:
    """The name of a rank number (Elite ranks), or the number when unknown."""
    names = RANKS.get(kind) or []
    if n is None:
        return None
    return names[n] if 0 <= n < len(names) else str(n)


def _numbers(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def build_statistics(archive: fl.Archive, days: Optional[float] = None,
                     now: Optional[float] = None) -> Dict[str, Any]:
    """The STATISTICS view from the game's Statistics events: ranks,
    reputation, the numbers and how much they grew over the period."""
    now = time.time() if now is None else now
    evs = archive.events()
    stats = [e for e in evs if e["event"] == "Statistics"]
    if not stats:
        return {"empty": True}
    last = stats[-1]
    out: Dict[str, Any] = {"ts": parse_ts(last.get("timestamp")), "days": days,
                           "first_ts": parse_ts(stats[0].get("timestamp")), "count": len(stats)}
    # the baseline: the last Statistics at or before the start of the period
    # (all: the oldest one in the journals)
    base = stats[0]
    if days:
        since = now - days * 86400
        older = [e for e in stats if (parse_ts(e.get("timestamp")) or 0) <= since]
        base = older[-1] if older else stats[0]
    out["since_ts"] = parse_ts(base.get("timestamp"))
    sections: Dict[str, Any] = {}
    delta: Dict[str, Any] = {}
    for sec in SECTIONS:
        cur = _numbers(last.get(sec) or {})
        if not cur:
            continue
        sections[sec] = cur
        old = _numbers(base.get(sec) or {})
        d = {k: v - old[k] for k, v in cur.items() if k in old and v != old[k]}
        if d and base is not last:
            delta[sec] = d
    out["sections"] = sections
    out["delta"] = delta
    rank = next((e for e in reversed(evs) if e["event"] == "Rank"), None) or {}
    prog = next((e for e in reversed(evs) if e["event"] == "Progress"), None) or {}
    out["ranks"] = [{"key": k, "rank": rank.get(k), "name": rank_name(k, rank.get(k)),
                     "progress": prog.get(k), "max": len(RANKS[k]) - 1}
                    for k in RANK_ORDER if rank.get(k) is not None]
    rep = next((e for e in reversed(evs) if e["event"] == "Reputation"), None) or {}
    out["reputation"] = {k: rep.get(k) for k in ("Federation", "Empire", "Alliance", "Independent")
                         if rep.get(k) is not None}
    # own measurements from the journal, next to the game's numbers
    ex = sections.get("Exploration") or {}
    if ex.get("Total_Hyperspace_Jumps"):
        out["derived"] = {"avg_jump": round(ex["Total_Hyperspace_Distance"] / ex["Total_Hyperspace_Jumps"], 1)}
    # ST1: over time, first discoveries per month, surface scans
    out["series"] = series(stats, now - days * 86400 if days else None)
    out["first_discoveries"] = first_discoveries(evs)
    out["dss"] = dss_tiles(evs, now - days * 86400 if days else None)
    return out
