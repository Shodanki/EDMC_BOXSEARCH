# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0 CARRIER > JUMP PLAN: the fleet carrier's jumps to a target, planned from
data on this PC, with the time and tritium of every jump.

* time: the countdown (CarrierJumpRequest -> DepartureTime) is learnt from
  the commander's own jumps; the cooldown after a jump is the public value
  (5 min: Elite Dangerous Fandom wiki, "Drake-Class Carrier", read
  19.11.2026). Your fastest next request after an arrival is shown beside it.
* nothing is sent to the game: the commander enters every jump in the
  carrier's galaxy map; the FIS only plans, counts and ticks off.
"""

from __future__ import annotations

import json
import math
import os
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .live import parse_ts

COOLDOWN_MIN = 5.0          # public value, see the module docstring
COUNTDOWN_PRIOR_MIN = 15.0  # until the first own jump is known
CARRIER_MAX_JUMP = 500.0


def _pct(vals: List[float], p: float) -> float:
    """The p-th percentile (0..1) of sorted values, linear between ranks."""
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    lo = int(math.floor(k))
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def _countdowns(evs: Iterable[Dict[str, Any]]) -> List[float]:
    """Minutes from each own CarrierJumpRequest to its DepartureTime (the
    request the game kept; a cancelled one still had its countdown)."""
    out = []
    for e in evs:
        if e.get("event") != "CarrierJumpRequest":
            continue
        a, b = parse_ts(e.get("timestamp")), parse_ts(e.get("DepartureTime"))
        if a is not None and b is not None and 0 < b - a < 6 * 3600:
            out.append((b - a) / 60.0)
    return sorted(out)


def _fastest_next(evs: Iterable[Dict[str, Any]]) -> Optional[float]:
    """Minutes from an arrival (the first CarrierJump/CarrierLocation at a
    requested target) to the next request - the shortest seen."""
    target, arrived, best = None, None, None
    for e in evs:
        ev = e.get("event")
        if ev == "CarrierJumpRequest":
            t = parse_ts(e.get("timestamp"))
            if arrived is not None and t is not None and t > arrived:
                gap = (t - arrived) / 60.0
                best = gap if best is None else min(best, gap)
            target, arrived = e.get("SystemName"), None
        elif ev in ("CarrierJump", "CarrierLocation") and target and e.get("StarSystem") == target:
            arrived, target = parse_ts(e.get("timestamp")), None
    return round(best, 1) if best is not None else None


def timing(evs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """How long a carrier jump takes: countdown learnt from your own jumps
    (median, the middle 80 % as the range, n) and the cooldown."""
    evs = list(evs)
    cd = _countdowns(evs)
    if cd:
        count = {"mid": round(_pct(cd, 0.5), 1), "lo": round(_pct(cd, 0.1), 1),
                 "hi": round(_pct(cd, 0.9), 1), "n": len(cd), "learnt": True}
    else:
        count = {"mid": COUNTDOWN_PRIOR_MIN, "lo": COUNTDOWN_PRIOR_MIN, "hi": COUNTDOWN_PRIOR_MIN,
                 "n": 0, "learnt": False}
    return {"countdown": count, "cooldown": COOLDOWN_MIN, "fastest_next": _fastest_next(evs),
            "per_jump": round(count["mid"] + COOLDOWN_MIN, 1)}


def trip_time(jumps: int, tm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Minutes for `jumps` carrier jumps: every jump its countdown, every
    one but the last its cooldown (a range from the countdown's range)."""
    if not jumps or jumps < 1:
        return None
    c = tm["countdown"]
    cool = (jumps - 1) * tm["cooldown"]
    return {"jumps": jumps, "mid": round(jumps * c["mid"] + cool), "lo": round(jumps * c["lo"] + cool),
            "hi": round(jumps * c["hi"] + cool), "n": c["n"]}


# ------------------------------------------------------------------ stars
def _dist(a: Any, b: Any) -> float:
    return math.dist(a, b)


class OwnStars:
    """Systems with exact positions from your own data (plugin database and
    journals), in 100-ly cells for quick neighbour queries."""

    CELL = 100.0
    src = "own"

    def __init__(self, systems: Iterable[Dict[str, Any]]) -> None:
        self.cells: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}
        self.by_name: Dict[str, Dict[str, Any]] = {}
        for s in systems:
            p = s.get("pos")
            if not s.get("name") or not p or s["name"] in self.by_name:
                continue
            item = {"name": s["name"], "id64": s.get("id64"), "pos": tuple(p), "src": self.src}
            self.by_name[s["name"]] = item
            self.cells.setdefault(self._cell(item["pos"]), []).append(item)

    def __len__(self) -> int:
        return len(self.by_name)

    def drop(self, ids: Iterable[int]) -> None:
        """Leave these id64s out (permit-locked systems)."""
        ids = set(ids)
        if not ids:
            return
        for key, items in self.cells.items():
            self.cells[key] = [s for s in items if s.get("id64") not in ids]
        self.by_name = {k: v for k, v in self.by_name.items() if v.get("id64") not in ids}

    def _cell(self, p: Sequence[float]) -> Tuple[int, int, int]:
        return (int(p[0] // self.CELL), int(p[1] // self.CELL), int(p[2] // self.CELL))

    def near(self, center: Sequence[float], radius: float) -> List[Dict[str, Any]]:
        """Systems within radius of center."""
        lo, hi = self._cell([c - radius for c in center]), self._cell([c + radius for c in center])
        out = []
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    out.extend(s for s in self.cells.get((x, y, z), ()) if _dist(s["pos"], center) <= radius)
        return out


class EddStars:
    """EDDiscovery's local star database (EDDSystem.sqlite) through the
    plugin's own reader - read only, on this PC, no network."""

    src = "edd"

    def __init__(self, source: Any) -> None:
        self.source = source
        self._permits: Optional[set] = None

    def permits(self) -> set:
        """id64s EDDiscovery lists as permit-locked (the plugin's reader, read
        once): a carrier cannot go there, so they are never a hop. Empty with
        an older plugin."""
        if self._permits is None:
            try:
                self._permits = set(getattr(self.source, "permit_ids", lambda: set())() or ())
            except Exception:
                self._permits = set()
        return self._permits

    def near(self, center: Sequence[float], radius: float) -> List[Dict[str, Any]]:
        """Systems within radius of center (names decoded by the plugin)."""
        try:
            rows = self.source.fetch(tuple(center), radius)
        except Exception:      # a locked or changing file: no candidates this time
            return []
        blocked = self.permits()
        return [{"name": r["name"], "id64": r.get("id64"), "pos": (r["x"], r["y"], r["z"]), "src": self.src}
                for r in rows if r.get("name") and r.get("id64") not in blocked]

    def by_id64(self, id64: int) -> Optional[Dict[str, Any]]:
        """One system by its id64, or None."""
        try:
            rows = self.source.lookup_id64([int(id64)]) or []
        except Exception:
            return None
        return next(({"name": r["name"], "id64": r["id64"], "pos": (r["x"], r["y"], r["z"]), "src": self.src}
                     for r in rows if r.get("name")), None)

    def by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """A system by its exact name: procgen ("Col 285 Sector XY-Z c6-5"),
        catalogue ("HIP 31330") or a proper name ("Colonia") - looked up by
        EDDiscovery's (sector, name) index, or None."""
        src = self.source
        cols, table = getattr(src, "cols", {}) or {}, getattr(src, "table", None)
        if getattr(src, "mode", "") != "edd2" or not table or not cols.get("nameid"):
            return None
        try:
            cx = src._connect()
        except Exception:
            return None
        if cx is None:
            return None
        try:
            for sector, nameid in _edd_keys(cx, name.strip()):
                hit = _edd_row(cx, src, cols, table, sector, nameid)
                if hit:
                    return dict(hit, name=name.strip(), src=self.src)
        except Exception:      # a locked or changing file
            return None
        finally:
            cx.close()
        return None


_STD, _NUM = 1 << 61, 1 << 60


def _std_nameid(rest: str) -> Optional[int]:
    """EDDiscovery's packed nameid of a procgen rest "XY-Z c6-5" (inverse of
    the plugin's sources.EDDiscoverySource.decode_nameid)."""
    import re
    m = re.match(r"^([A-Z])([A-Z])-([A-Z]) ([a-h])(?:(\d+)-)?(\d+)$", rest)
    if not m:
        return None
    l1, l2, l3 = (ord(c) - 64 for c in m.group(1, 2, 3))
    mc = "abcdefgh".index(m.group(4))
    n1, n2 = int(m.group(5) or 0), int(m.group(6))
    if n1 > 0xFF or n2 > 0xFFFF:
        return None
    return _STD | n2 | (n1 << 16) | (mc << 24) | (l3 << 28) | (l2 << 33) | (l1 << 38)


def _num_nameid(rest: str) -> Optional[int]:
    """The packed nameid of a catalogue number "31330" or "1846-031"."""
    if not rest or rest.count("-") > 1 or not rest.replace("-", "").isdigit():
        return None
    digits = rest.replace("-", "")
    dash = rest.index("-") + 1 if "-" in rest else 0
    if len(digits) > 15 or dash > 15:
        return None
    return _NUM | int(digits) | (len(digits) << 42) | (dash << 38)


def _edd_keys(cx: Any, name: str) -> List[Tuple[str, int]]:
    """(sector, nameid) pairs a name may be stored under."""
    words = name.split(" ")
    keys: List[Tuple[str, int]] = []
    for cut in range(len(words) - 1, 0, -1):
        sector, rest = " ".join(words[:cut]), " ".join(words[cut:])
        for nid in (_std_nameid(rest), _num_nameid(rest)):
            if nid is not None:
                keys.append((sector, nid))
    for sector, rest in [("NoSectorName", name)] + [(" ".join(words[:c]), " ".join(words[c:]))
                                                    for c in range(1, len(words))]:
        row = cx.execute("SELECT id FROM Names WHERE Name = ?", (rest,)).fetchone()
        if row:
            keys.append((sector, int(row[0])))
    return keys


def _edd_row(cx: Any, src: Any, cols: Dict[str, str], table: str, sector: str, nameid: int
             ) -> Optional[Dict[str, Any]]:
    ids = [r[0] for r in cx.execute("SELECT id FROM Sectors WHERE name = ?", (sector,))]
    if not ids:
        return None
    key = (",%s" % cols["key"]) if cols.get("key") else ""
    q = ("SELECT %s,%s,%s%s FROM %s WHERE %s IN (%s) AND %s = ? LIMIT 1"
         % (cols["x"], cols["y"], cols["z"], key, table, cols["sectorid"], ",".join("?" * len(ids)), cols["nameid"]))
    r = cx.execute(q, ids + [nameid]).fetchone()
    if not r:
        return None
    pos = tuple((v - src.offset) / src.scale for v in r[:3])
    return {"id64": int(r[3]) if len(r) > 3 and r[3] else None, "pos": pos}


def edd_stars(path: Optional[str]) -> Optional[EddStars]:
    """EddStars when the plugin's EDD reader and EDDSystem.sqlite are there
    and its coordinates are calibrated, else None."""
    try:
        import sources  # type: ignore   # the plugin's module (FIS sets sys.path)
    except ImportError:
        return None
    src = sources.EDDiscoverySource(path or None)
    try:
        ok, _why = src.available()
    except Exception:
        return None
    return EddStars(src) if ok else None


# ------------------------------------------------------------------ route
def _corridor(own: OwnStars, a: Sequence[float], b: Sequence[float], jump: float) -> List[Dict[str, Any]]:
    """Own systems in an ellipse around the line a-b (a jump wide)."""
    d = _dist(a, b)
    mid = [(a[i] + b[i]) / 2 for i in range(3)]
    return [s for s in own.near(mid, d / 2 + jump) if _dist(a, s["pos"]) + _dist(s["pos"], b) <= d + 2 * jump]


def route_own(start: Dict[str, Any], target: Dict[str, Any], own: OwnStars,
              jump: float = CARRIER_MAX_JUMP) -> Optional[List[Dict[str, Any]]]:
    """Fewest jumps over your own systems only (breadth first), or None."""
    a, b = start["pos"], target["pos"]
    if _dist(a, b) <= jump:
        return [target]
    nodes = [n for n in _corridor(own, a, b, jump) if n["name"] != target["name"]] + [target]
    grid = OwnStars([])
    grid.CELL = jump
    for n in nodes:
        grid.cells.setdefault(grid._cell(n["pos"]), []).append(n)
    prev: Dict[str, Optional[Dict[str, Any]]] = {start["name"]: None}
    frontier = [start]
    while frontier:
        nxt = []
        for cur in sorted(frontier, key=lambda s: _dist(s["pos"], b)):
            for n in grid.near(cur["pos"], jump):
                if n["name"] in prev:
                    continue
                prev[n["name"]] = cur
                if n is target:
                    return _back(prev, target)
                nxt.append(n)
        frontier = nxt
    return None


def _back(prev: Dict[str, Any], last: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = [last]
    while prev.get(path[-1]["name"]) is not None:
        path.append(prev[path[-1]["name"]])
    return list(reversed(path[:-1]))


SEARCH_RADII = (10.0, 25.0, 60.0, 150.0, 300.0)


def _best_step(cur: Sequence[float], b: Sequence[float], finders: Sequence[Any], jump: float
               ) -> Optional[Dict[str, Any]]:
    """The reachable system nearest the target around the ideal point one
    full jump ahead, searched in growing radii."""
    d = _dist(cur, b)
    ideal = [cur[i] + (b[i] - cur[i]) * jump / d for i in range(3)]
    for rad in SEARCH_RADII:
        cand = [s for f in finders for s in f.near(ideal, rad)
                if _dist(s["pos"], cur) <= jump and _dist(s["pos"], b) < d - 1.0]
        if cand:
            return min(cand, key=lambda s: (_dist(s["pos"], b), s["src"] != "own"))
    return None


def route_greedy(start: Dict[str, Any], target: Dict[str, Any], finders: Sequence[Any],
                 jump: float = CARRIER_MAX_JUMP, limit: int = 400) -> Optional[List[Dict[str, Any]]]:
    """Full jumps along the line to the target over every finder's systems
    (own first on a tie), or None when there is a gap."""
    cur, b, hops = start["pos"], target["pos"], []
    while _dist(cur, b) > jump:
        step = _best_step(cur, b, finders, jump)
        if step is None or len(hops) >= limit:
            return None
        hops.append(step)
        cur = step["pos"]
    hops.append(target)
    return hops


def plan_route(start: Dict[str, Any], target: Dict[str, Any], own: OwnStars,
               edd: Optional[Any] = None, jump: float = CARRIER_MAX_JUMP) -> Dict[str, Any]:
    """Your own systems first; with EDDiscovery's star database the route is
    checked and, where it needs fewer jumps or own data has a gap, extended.
    {"hops", "source": own | own+edd | None, "checked_edd", "own_jumps"}."""
    mine = route_own(start, target, own, jump)
    out: Dict[str, Any] = {"hops": mine, "source": "own" if mine else None, "checked_edd": edd is not None,
                           "own_jumps": len(mine) if mine else None,
                           "ideal": math.ceil(_dist(start["pos"], target["pos"]) / jump)}
    if edd is not None:
        both = route_greedy(start, target, [own, edd], jump)
        if both and (not mine or len(both) < len(mine)):
            out.update(hops=both, source="own+edd" if any(h.get("src") == "edd" for h in both) else "own")
    return out


# ------------------------------------------------------------------ tritium
def fuel_rows(legs: Sequence[float], load: float, tank: int, hold: int,
              tank_max: int = 1000) -> List[Dict[str, Any]]:
    """Tritium per jump with the tank going down, and when tritium must move
    from the hold into the active tank: before a jump the tank cannot pay,
    the tank is filled up from the hold (the least is named too). Tritium in
    the hold is cargo: moving it changes the load, not the mass."""
    from .fleet import tritium_for_jump
    rows = []
    for ly in legs:
        need = tritium_for_jump(ly, load, tank)
        row: Dict[str, Any] = {"ly": round(ly, 1), "need": need, "tank_before": tank}
        if need > tank:
            fill = min(hold, tank_max - tank)
            row["refuel"] = {"min": need - tank, "fill": fill, "short": max(0, need - tank - fill)}
            tank, hold, load = tank + fill, hold - fill, max(0.0, load - fill)
        tank = tank - need
        row["tank_after"] = max(0, tank)
        row["short"] = tank < 0
        tank = max(0, tank)
        rows.append(row)
    return rows


# ------------------------------------------------------------------ the plan file
class PlanStore:
    """FIS/jump_plan.json (personal - never in the repository), per commander
    (FID): the current plan and your "target full" reports. Written
    atomically (temporary file + os.replace); a broken file is set aside."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) and isinstance(d.get("cmdrs"), dict) else {"cmdrs": {}}
        except FileNotFoundError:
            return {"cmdrs": {}}
        except (OSError, ValueError):
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return {"cmdrs": {}}

    def _save(self, d: Dict[str, Any]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def get(self, fid: Optional[str]) -> Dict[str, Any]:
        """{"plan": ... or None, "full": [...]} of a commander."""
        with self._lock:
            c = self._load()["cmdrs"].get(fid or "?") or {}
        return {"plan": c.get("plan"), "full": list(c.get("full") or [])}

    def _change(self, fid: Optional[str], fn) -> Dict[str, Any]:
        with self._lock:
            d = self._load()
            c = d["cmdrs"].setdefault(fid or "?", {})
            fn(c)
            self._save(d)
            return c

    def set_plan(self, fid: Optional[str], plan: Optional[Dict[str, Any]]) -> None:
        """Replace (or with None drop) the plan."""
        self._change(fid, lambda c: c.__setitem__("plan", plan))

    def report_full(self, fid: Optional[str], rep: Dict[str, Any], keep: int = 200) -> None:
        """A "target full" report; the newest `keep` are kept."""
        def add(c: Dict[str, Any]) -> None:
            c["full"] = (list(c.get("full") or []) + [rep])[-keep:]
        self._change(fid, add)


# ------------------------------------------------------------------ ticking off
def progress(hops: Sequence[Dict[str, Any]], carrier_evs: Iterable[Dict[str, Any]],
             since: Optional[float]) -> Dict[int, str]:
    """hop index -> arrival time, from your carrier's own CarrierJump /
    CarrierLocation after the plan was made, in the plan's order (a hop
    skipped is not ticked; a later one is)."""
    done: Dict[int, str] = {}
    nxt = 0
    names = [h.get("name") for h in hops]
    for e in carrier_evs:
        if e.get("event") not in ("CarrierJump", "CarrierLocation"):
            continue
        ts = parse_ts(e.get("timestamp"))
        if since is not None and (ts is None or ts <= since):
            continue
        sysname = e.get("StarSystem")
        if sysname in names[nxt:]:
            k = names.index(sysname, nxt)
            done[k] = e.get("timestamp")
            nxt = k + 1
    return done


# ------------------------------------------------------------------ building the plan
def own_stars(db: Any, evs: Iterable[Dict[str, Any]]) -> OwnStars:
    """Your systems with exact positions: the journals first, then the
    plugin database."""
    from .live import star_pos
    items: List[Dict[str, Any]] = []
    for e in evs:
        p = star_pos(e.get("StarPos"))
        if p and e.get("StarSystem"):
            items.append({"name": e["StarSystem"], "id64": e.get("SystemAddress"), "pos": p})
    items.reverse()      # the newest report of a name wins
    if db is not None and db.exists:
        for r in db.query("SELECT name, id64, x, y, z FROM systems WHERE x IS NOT NULL"):
            items.append({"name": r["name"], "id64": r["id64"], "pos": (r["x"], r["y"], r["z"])})
    return OwnStars(items)


def resolve(own: OwnStars, edd: Optional[EddStars], name: Optional[str] = None,
            id64: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """A target from your data, else from EDDiscovery's star database."""
    if name:
        hit = own.by_name.get(name.strip()) or next(
            (s for k, s in own.by_name.items() if k.lower() == name.strip().lower()), None)
        if hit:
            return dict(hit)
    if id64:
        hit = next((s for s in own.by_name.values() if s.get("id64") == int(id64)), None)
        if hit:
            return dict(hit)
    if edd is not None:
        return (edd.by_id64(id64) if id64 else None) or (edd.by_name(name) if name else None)
    return None


def make_plan(start: Dict[str, Any], target: Dict[str, Any], own: OwnStars, edd: Optional[Any],
              now: float, body: Optional[str] = None, body_id: Optional[int] = None) -> Dict[str, Any]:
    """A new plan from the carrier's position to the target (or the reason
    there is none: then Spansh can plan it)."""
    r = plan_route(start, target, own, edd)
    hops = [{"name": h["name"], "id64": h.get("id64"), "pos": list(h["pos"]), "src": h.get("src", "own")}
            for h in (r["hops"] or [])]
    if r["source"] == "own" and any(h["src"] == "edd" for h in hops):
        r["source"] = "own+edd"          # the target itself came from EDDiscovery
    return {"created": now, "start": {"name": start["name"], "pos": list(start["pos"])},
            "target": {"name": target["name"], "id64": target.get("id64"), "pos": list(target["pos"]),
                       "body": body, "body_id": body_id},
            "hops": hops, "source": r["source"], "checked_edd": r["checked_edd"],
            "own_jumps": r["own_jumps"], "ideal": r["ideal"], "own_systems": len(own)}


def _legs(start: Sequence[float], hops: Sequence[Dict[str, Any]]) -> List[Optional[float]]:
    out, cur = [], start
    for h in hops:
        p = h.get("pos")
        out.append(_dist(cur, p) if cur and p else h.get("ly"))
        cur = p or None
    return out


def build(plan: Optional[Dict[str, Any]], carrier: Optional[Dict[str, Any]], carrier_evs: List[Dict[str, Any]],
          hold: int, now: float) -> Dict[str, Any]:
    """The JUMP PLAN view: every jump with tritium, time and the refuelling
    moments from the carrier's state now; jumps done are ticked off."""
    tm = timing(carrier_evs)
    out: Dict[str, Any] = {"timing": tm, "plan": plan, "rows": [], "hold": hold}
    if not plan or not plan.get("hops"):
        return out
    hops = plan["hops"]
    done = progress(hops, carrier_evs, plan.get("created"))
    nxt = max(done) + 1 if done else 0
    legs = _legs(plan["start"]["pos"], hops)
    fuel = fuel_rows([lg or 0.0 for lg in legs[nxt:]], (carrier or {}).get("load") or 0,
                     int((carrier or {}).get("fuel") or 0), hold)
    clock = 0.0
    for i, h in enumerate(hops):
        row = {"i": i + 1, "name": h["name"], "id64": h.get("id64"), "src": h.get("src"),
               "ly": round(legs[i], 1) if legs[i] is not None else None, "done": done.get(i), "next": i == nxt,
               "spansh_fuel": h.get("spansh_fuel"), "icy_ring": h.get("icy_ring")}
        if i >= nxt:
            f = fuel[i - nxt]
            last = i == len(hops) - 1
            clock += tm["countdown"]["mid"] + (0 if last else tm["cooldown"])
            row.update(need=f["need"], tank_after=f["tank_after"], refuel=f.get("refuel"), short=f["short"],
                       minutes=round(tm["countdown"]["mid"] + (0 if last else tm["cooldown"]), 1),
                       at=round(clock))
        out["rows"].append(row)
    left = len(hops) - nxt
    out.update(left=left, total=trip_time(left, tm), need=sum(r.get("need") or 0 for r in out["rows"]),
               arrived=nxt >= len(hops))
    return out


# ------------------------------------------------------------------ Spansh
SPANSH_ROUTER = "https://spansh.co.uk/fleet-carrier"


def _spansh_json(d: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Jumps of Spansh's fleet carrier JSON export (result.jumps)."""
    res = d.get("result") if isinstance(d.get("result"), dict) else d
    jumps = res.get("jumps") if isinstance(res, dict) else None
    if not isinstance(jumps, list):
        return None
    out = []
    for j in jumps:
        if not isinstance(j, dict) or not j.get("name"):
            return None
        pos = [j.get("x"), j.get("y"), j.get("z")]
        out.append({"name": str(j["name"])[:80], "id64": _int(j.get("id64")),
                    "pos": pos if all(isinstance(v, (int, float)) for v in pos) else None,
                    "ly": _num(j.get("distance")), "spansh_fuel": _int(j.get("fuel_used")),
                    "restock": bool(j.get("must_restock")), "icy_ring": bool(j.get("has_icy_ring")),
                    "pristine": bool(j.get("is_system_pristine"))})
    return out


def _spansh_csv(text: str) -> Optional[List[Dict[str, Any]]]:
    """Jumps of Spansh's fleet carrier CSV export (names and distances)."""
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "System Name" not in rows[0]:
        return None
    yes = ("yes", "true", "1")
    return [{"name": r["System Name"][:80], "id64": None, "pos": None, "ly": _num(r.get("Distance")),
             "spansh_fuel": _int(r.get("Fuel Used")), "restock": (r.get("Restock Tritium") or "").lower() in yes,
             "icy_ring": (r.get("Icy Ring") or "").lower() in yes, "pristine": (r.get("Pristine") or "").lower() in yes}
            for r in rows if r.get("System Name")]


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_spansh(text: str) -> Optional[List[Dict[str, Any]]]:
    """Spansh's fleet carrier route, JSON or CSV, as a list of jumps with
    the start first - or None when it is neither."""
    text = (text or "").lstrip("\ufeff").strip()
    if text.startswith("{"):
        try:
            d = json.loads(text)
        except ValueError:
            return None
        return _spansh_json(d) if isinstance(d, dict) else None
    return _spansh_csv(text)


def spansh_plan(jumps: List[Dict[str, Any]], own: OwnStars, edd: Optional[Any], now: float
                ) -> Optional[Dict[str, Any]]:
    """A plan from an imported Spansh route: the first row is the start;
    positions missing in a CSV come from your data or EDDiscovery's."""
    if len(jumps) < 2:
        return None
    for j in jumps:
        if j["pos"] is None:
            hit = resolve(own, edd, name=j["name"], id64=j.get("id64"))
            j["pos"] = list(hit["pos"]) if hit else None
            j["id64"] = j.get("id64") or (hit or {}).get("id64")
    start, hops = jumps[0], jumps[1:]
    tgt = hops[-1]
    return {"created": now, "start": {"name": start["name"], "pos": start["pos"]},
            "target": {"name": tgt["name"], "id64": tgt.get("id64"), "pos": tgt["pos"], "body": None, "body_id": None},
            "hops": [dict(h, src="spansh") for h in hops], "source": "spansh", "checked_edd": False,
            "own_jumps": None, "ideal": None, "own_systems": len(own),
            "spansh_need": sum(h.get("spansh_fuel") or 0 for h in hops)}


def spansh_help(carrier: Optional[Dict[str, Any]], plan: Optional[Dict[str, Any]], hold: int) -> Dict[str, Any]:
    """What Spansh's fleet carrier router asks for, ready to copy: source,
    destination, used capacity (TotalCapacity - FreeSpace of CarrierStats),
    tritium in the tank and in the hold. Spansh opens in your own browser."""
    c = carrier or {}
    dest = ((plan or {}).get("target") or {}).get("name")
    return {"url": SPANSH_ROUTER, "source": c.get("system"), "destination": dest,
            "used": c.get("used"), "tank": c.get("fuel"), "hold": hold}


# ------------------------------------------------------------------ target full
DAY = 86400.0
SEEN_WINDOW = 30 * DAY        # carriers seen in a system count this long
LEARN_WINDOW = 180 * DAY      # how far back "full" and "got in" are learnt
FULL_FRESH = DAY              # a "full" report this new is shown as such
MIN_FULL = 3                  # "full" reports before an estimate is given
DEFAULT_LADEN = 20.0          # ly, when no transporter rated 4-5 is on board


def sightings(evs: Iterable[Dict[str, Any]]) -> Dict[int, List[Tuple[float, str]]]:
    """System id64 -> (time, callsign) of every carrier you saw there in
    the FSS (FSSSignalDiscovered)."""
    from .carriers import parse_signal
    out: Dict[int, List[Tuple[float, str]]] = {}
    for e in evs:
        if e.get("event") != "FSSSignalDiscovered" or not e.get("SystemAddress"):
            continue
        sig = parse_signal(e.get("SignalName"))
        ts = parse_ts(e.get("timestamp"))
        if sig and ts is not None:
            out.setdefault(int(e["SystemAddress"]), []).append((ts, sig["callsign"]))
    return out


def seen_at(sight: Dict[int, List[Tuple[float, str]]], id64: Optional[int], at: float) -> int:
    """Different carriers you saw in a system in the 30 days before `at`."""
    if not id64:
        return 0
    return len({cs for ts, cs in sight.get(int(id64), ()) if at - SEEN_WINDOW <= ts <= at})


def arrivals(carrier_evs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every time your carrier got into the system it was sent to (the
    first CarrierJump/CarrierLocation there after a CarrierJumpRequest)."""
    out, target = [], None
    for e in carrier_evs:
        ev = e.get("event")
        if ev == "CarrierJumpRequest":
            target = e.get("SystemName")
        elif ev in ("CarrierJump", "CarrierLocation") and target and e.get("StarSystem") == target:
            out.append({"system": target, "id64": e.get("SystemAddress"), "ts": parse_ts(e.get("timestamp"))})
            target = None
    return out


def full_estimate(target: Dict[str, Any], reports: List[Dict[str, Any]], got_in: List[Dict[str, Any]],
                  sight: Dict[int, List[Tuple[float, str]]], now: float) -> Dict[str, Any]:
    """How likely the target is full, learnt from your own reports ("full",
    by hand) and arrivals (got in, from the journal), each with the carriers
    you had seen there then. A system fills and empties within minutes, so
    this is only a hint: unknown until MIN_FULL reports exist."""
    seen = seen_at(sight, target.get("id64"), now)
    recent = [r for r in reports if r.get("ts") and now - r["ts"] <= LEARN_WINDOW]
    obs = [(r.get("seen") or 0, True) for r in recent]
    obs += [(seen_at(sight, a.get("id64"), a["ts"]), False) for a in got_in
            if a.get("ts") and now - a["ts"] <= LEARN_WINDOW]
    mine = [r["ts"] for r in recent if _same(r, target)]
    out: Dict[str, Any] = {"seen": seen, "reports": len(recent), "arrivals": len(obs) - len(recent),
                           "reported_full": max(mine) if mine else None}
    alike = [full for s, full in obs if s >= seen]
    if len(recent) < MIN_FULL or not alike:
        out["state"] = "unknown"
        return out
    p = sum(alike) / len(alike)
    out.update(state="likely full" if p >= 0.5 else "likely free", p=round(100 * p), n=len(alike))
    return out


def _same(r: Dict[str, Any], target: Dict[str, Any]) -> bool:
    if r.get("id64") and target.get("id64"):
        return int(r["id64"]) == int(target["id64"])
    return (r.get("system") or "").lower() == (target.get("name") or "").lower()


# ------------------------------------------------------------------ alternatives
def laden_seen(evs: Iterable[Dict[str, Any]]) -> Dict[Tuple[int, Any], Tuple[float, int]]:
    """(ship id, fitting time) -> (longest jump, jumps) flown with the hold
    at least 90 % full - your own laden jumps."""
    out: Dict[Tuple[int, Any], Tuple[float, int]] = {}
    sid, lo_ts, cap, cargo = None, None, 0, 0
    for e in evs:
        ev = e.get("event")
        if ev == "Loadout" and e.get("ShipID") is not None:
            sid, lo_ts, cap = int(e["ShipID"]), e.get("timestamp"), e.get("CargoCapacity") or 0
        elif ev == "Cargo" and e.get("Vessel", "Ship") == "Ship":
            cargo = e.get("Count") or 0
        elif ev == "FSDJump" and sid is not None and cap >= 8 and cargo >= 0.9 * cap and e.get("JumpDist"):
            best, n = out.get((sid, lo_ts), (0.0, 0))
            out[(sid, lo_ts)] = (max(best, float(e["JumpDist"])), n + 1)
    return out


def transporters(ships: Iterable[Dict[str, Any]], seen: Dict[Tuple[int, Any], Tuple[float, int]]
                 ) -> List[Dict[str, Any]]:
    """Ships on board (or flown now) rated 4-5 for transport, with their
    laden jump range: your own laden jumps with this fitting first, else
    ~ the empty range x unladen mass / (unladen mass + fuel + full hold) -
    the range falls with the mass. Shortest first."""
    out = []
    for s in ships:
        r = (s.get("rating") or {}).get("roles") or {}
        if r.get("transport", 0) < 4 or not (s.get("stored_at") == "here" or s.get("current")):
            continue
        obs = seen.get((s.get("id"), s.get("loadout_ts")))
        m, f, c, j = s.get("mass"), s.get("fuel_cap") or 0, s.get("cargo") or 0, s.get("jump")
        est = j * m / (m + f + c) if j and m else None
        rng, src = (obs[0], "seen") if obs else (est, "estimate")
        if rng:
            out.append({"id": s.get("id"), "name": s.get("name") or s.get("type_name"), "type": s.get("type_name"),
                        "stars": r["transport"], "cargo": c, "empty": j, "laden": round(rng, 1), "src": src,
                        "n": obs[1] if obs else 0})
    return sorted(out, key=lambda x: x["laden"])


def alternatives(target: Dict[str, Any], before: Sequence[float], finders: Sequence[Any], laden: float,
                 fewest: bool, avoid: Iterable[str], sight: Dict[int, List[Tuple[float, str]]], now: float,
                 jump: float = CARRIER_MAX_JUMP, limit: int = 12) -> List[Dict[str, Any]]:
    """Systems near a full target the carrier can reach from the jump before
    it. With `fewest` only those one laden ship jump away, fewest carriers
    seen first; otherwise up to three ship jumps, nearest first."""
    radius = laden if fewest else 3 * laden
    skip = {a.lower() for a in avoid} | {target["name"].lower()}
    found: Dict[str, Dict[str, Any]] = {}
    for f in finders:
        for s in f.near(target["pos"], radius):
            if s["name"].lower() in skip or s["name"] in found or _dist(s["pos"], before) > jump:
                continue
            d = _dist(s["pos"], target["pos"])
            found[s["name"]] = {"name": s["name"], "id64": s.get("id64"), "pos": list(s["pos"]), "ly": round(d, 1),
                                "ship_jumps": max(1, math.ceil(d / laden)), "seen": seen_at(sight, s.get("id64"), now),
                                "src": s.get("src", "own")}
    if fewest:
        return sorted(found.values(), key=lambda a: (a["ship_jumps"], a["seen"], a["ly"]))[:limit]
    return sorted(found.values(), key=lambda a: (a["ly"], a["seen"]))[:limit]


BUBBLE_LY = 1000.0            # "the bubble": within this of Sol


def in_bubble(pos: Sequence[float]) -> bool:
    """True for a position within BUBBLE_LY of Sol."""
    return _dist(pos, (0.0, 0.0, 0.0)) <= BUBBLE_LY


def carriers_in(res: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """From Spansh's carriers near the target (nearest first, at most
    online.NEARBY_SIZE): those in the target system itself."""
    from .online import NEARBY_SIZE
    cs = res.get("carriers") or []
    here = [c for c in cs if (c.get("system") or "").lower() == target["name"].lower()
            or (c.get("distance") is not None and c["distance"] < 0.5)]
    return {"count": len(here), "capped": len(here) >= NEARBY_SIZE, "checked": res.get("checked"),
            "cached": res.get("cached"), "callsigns": [c.get("callsign") for c in here]}
