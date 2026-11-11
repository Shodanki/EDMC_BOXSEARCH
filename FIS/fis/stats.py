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


def rank_name(kind: str, n: Optional[int]) -> Optional[str]:
    names = RANKS.get(kind) or []
    if n is None:
        return None
    return names[n] if 0 <= n < len(names) else str(n)


def _numbers(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def build_statistics(archive: fl.Archive, days: Optional[float] = None,
                     now: Optional[float] = None) -> Dict[str, Any]:
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
    return out
