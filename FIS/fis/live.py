"""Follows the journal, Status.json and NavRoute.json - read only.

Polling (default 0.5 s) instead of file-system notifications: standard library
only, and it works the same on a network share. Each recognised change is
published to a Hub, which the HTTP server turns into Server-Sent Events.
"""

from __future__ import annotations

import copy
import glob
import json
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


def parse_ts(stamp: Optional[str]) -> Optional[float]:
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Event hub (one queue per SSE client)
# ---------------------------------------------------------------------------

class Hub:
    def __init__(self, maxsize: int = 200) -> None:
        self._subs: List[queue.Queue] = []
        self._lock = threading.Lock()
        self.maxsize = maxsize
        self.published = 0

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(self.maxsize)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, event: str, data: Any) -> None:
        self.published += 1
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                # a stalled client loses events rather than blocking the game feed
                pass


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

SCAN_EVENTS = {"Scan", "FSSDiscoveryScan", "FSSAllBodiesFound", "SAAScanComplete",
               "FSSBodySignals", "SAASignalsFound", "ScanOrganic", "ScanBaryCentre",
               "CodexEntry"}
FIX_EVENTS = {"ApproachBody", "SupercruiseExit", "Touchdown", "Liftoff",
              "SAAScanComplete", "ScanOrganic", "Disembark", "Embark",
              "ApproachSettlement", "LeaveBody"}


def empty_state() -> Dict[str, Any]:
    return {
        "commander": None,
        "ship": {},
        "system": {},           # name, id64, pos, ts
        "target": None,         # FSDTarget: name, id64, star_class, remaining_jumps
        "ship_target": None,    # ShipTargeted: the locked ship, as far as scanned (E5)
        "vehicle": None,        # surface vehicle out now: "SRV Rhino", "Nomad" ... (M2)
        "navroute": [],         # NavRoute.json hops
        "fuel": {},             # main, reservoir
        "status": {},           # Status.json, decoded
        "last_fix": None,       # body, body_id, system_id64, event, ts, lat/lon/alt
        "jumping": None,        # StartJump hyperspace until FSDJump
        "jumps": [],            # (distance ly, fuel used t) for the fuel model
        "loadout": None,        # last Loadout event, full (modules, health, ammo)
        "alerts": [],           # ship alerts of this session: heat, breach, AFMU ...
        "journal": None,        # file being followed
        "last_event": None, "last_event_ts": None,
    }


class LiveTracker:
    """Owns the live state. `feed()` and `feed_status()` are pure enough to
    unit-test; `start()` runs the polling thread against real files."""

    def __init__(self, journal_dir: str, hub: Optional[Hub] = None,
                 poll_s: float = 0.5) -> None:
        self.journal_dir = journal_dir
        self.hub = hub or Hub()
        self.poll_s = poll_s
        self._lock = threading.RLock()
        self.state = empty_state()
        self._file: Optional[str] = None
        self._offset = 0
        self._partial = b""
        self._status_sig: Optional[tuple] = None
        self._nav_sig: Optional[tuple] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._replaying = False
        self.errors = 0
        # watchdog: when the polling last ran, how often the game rewrote the
        # journal under the same name (06.11.2026: after a lost connection the
        # game started the file anew; reading on at the old offset, past the
        # new end, the FIS heard nothing until it was restarted)
        self._head: Optional[bytes] = None
        self.last_poll = 0.0
        self.rewrites = 0

    # ---------------------------------------------------------------- api
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.state)

    def _emit(self, event: str, data: Any) -> None:
        if not self._replaying:
            self.hub.publish(event, data)

    # ---------------------------------------------------------- journal
    def feed(self, e: Dict[str, Any]) -> Optional[str]:
        """Apply one journal entry. Returns the SSE event name it caused."""
        ev = e.get("event")
        ts = parse_ts(e.get("timestamp"))
        s = self.state
        out: Optional[str] = None
        with self._lock:
            s["last_event"], s["last_event_ts"] = ev, ts
            if ev == "Commander":
                s["commander"] = e.get("Name")
            elif ev == "LoadGame":
                s["commander"] = e.get("Commander") or s["commander"]
                s["ship_target"] = None      # new game session: no lock yet
                s["vehicle"] = None
                s["ship"].update(type=e.get("Ship"), name=e.get("ShipName"),
                                 ident=e.get("ShipIdent"))
                if e.get("FuelCapacity"):
                    s["ship"]["fuel_capacity"] = e.get("FuelCapacity")
                if e.get("FuelLevel") is not None:
                    s["fuel"]["main"] = e.get("FuelLevel")
                out = "status"
            elif ev == "Loadout":
                s["loadout"] = e
                fc = e.get("FuelCapacity") or {}
                s["ship"].update(type=e.get("Ship"), name=e.get("ShipName"),
                                 ident=e.get("ShipIdent"),
                                 max_jump=e.get("MaxJumpRange"),
                                 hull=e.get("HullHealth"),
                                 fuel_capacity=fc.get("Main") if isinstance(fc, dict) else fc,
                                 reserve_capacity=fc.get("Reserve") if isinstance(fc, dict) else None)
                out = "status"
            elif ev in ("Location", "FSDJump", "CarrierJump"):
                new_id = e.get("SystemAddress")
                changed = new_id != s["system"].get("id64")
                s["system"] = {"name": e.get("StarSystem"), "id64": new_id,
                               "pos": e.get("StarPos"), "ts": ts}
                if ev == "FSDJump":
                    if e.get("FuelLevel") is not None:
                        s["fuel"]["main"] = e.get("FuelLevel")
                    d, u = e.get("JumpDist"), e.get("FuelUsed")
                    if d and u:
                        s["jumps"].append([float(d), float(u)])
                        del s["jumps"][:-60]
                s["jumping"] = None
                s["ship_target"] = None      # a lock never survives a jump
                if s["target"] and s["target"].get("id64") == new_id:
                    s["target"] = None
                if e.get("BodyID") is not None and e.get("BodyType") not in (None, "Star", "Null") \
                        and ev != "FSDJump":
                    s["last_fix"] = {"body": e.get("Body"), "body_id": e.get("BodyID"),
                                     "system_id64": new_id, "event": ev, "ts": ts}
                elif changed or ev == "FSDJump":
                    # arrival: the fix is the arrival star (resolved by the model)
                    s["last_fix"] = {"body": None, "body_id": None,
                                     "system_id64": new_id, "event": ev, "ts": ts}
                out = "jump"
            elif ev == "StartJump":
                if e.get("JumpType") == "Hyperspace":
                    s["jumping"] = {"name": e.get("StarSystem"), "id64": e.get("SystemAddress"),
                                    "star_class": e.get("StarClass"), "ts": ts}
                    if s["target"] and s["target"].get("id64") == e.get("SystemAddress"):
                        s["target"]["star_class"] = e.get("StarClass")
                    out = "target"
            elif ev in ("LaunchSRV", "LaunchVessel"):
                s["vehicle"] = (e.get("SRVType_Localised") or e.get("VesselType_Localised")
                                or e.get("SRVType") or e.get("VesselType") or "SRV")
                out = "status"
            elif ev in ("DockSRV", "DockVessel", "SRVDestroyed"):
                s["vehicle"] = None
                out = "status"
            elif ev == "ShipTargeted":
                s["ship_target"] = self._ship_target(e, s.get("ship_target"), ts)
                out = "target"
            elif ev in ("SupercruiseEntry", "Died", "Shutdown") and s.get("ship_target"):
                s["ship_target"] = None
                out = "target"
            elif ev == "FSDTarget":
                s["target"] = {"name": e.get("Name"), "id64": e.get("SystemAddress"),
                               "star_class": e.get("StarClass"),
                               "remaining_jumps": e.get("RemainingJumpsInRoute"),
                               "source": "FSDTarget", "ts": ts}
                out = "target"
            elif ev == "NavRoute":
                if e.get("Route"):
                    s["navroute"] = self._hops(e["Route"])
                elif not self._replaying:
                    self._read_navroute(force=True)
                out = "target"
            elif ev == "NavRouteClear":
                s["navroute"] = []
                out = "target"
            elif ev == "FuelScoop":
                if e.get("Total") is not None:
                    s["fuel"]["main"] = e.get("Total")
                out = "status"
            elif ev == "ReservoirReplenished":
                s["fuel"]["main"] = e.get("FuelMain")
                s["fuel"]["reservoir"] = e.get("FuelReservoir")
            elif ev == "HullDamage":
                # the ship's hull (not a fighter's): Health 0..1
                if e.get("PlayerPilot") and not e.get("Fighter") and e.get("Health") is not None:
                    s["ship"]["hull"] = e.get("Health")
                    out = "status"
            elif ev == "ShieldState":
                s["ship"]["shields_up"] = bool(e.get("ShieldsUp"))
                out = "status"
            elif ev in ("HeatWarning", "HeatDamage", "CockpitBreached", "SystemsShutdown",
                        "AfmuRepairs"):
                s["alerts"].append({"event": ev, "ts": ts,
                                    "module": e.get("Module_Localised") or e.get("Module"),
                                    "module_key": e.get("Module"),
                                    "health": e.get("Health")})
                del s["alerts"][:-40]
                out = "status"
            elif ev in ("RepairAll", "Repair") or (ev == "Docked"):
                # repaired / docked: a breach is history now
                s["alerts"] = [a for a in s["alerts"] if a["event"] != "CockpitBreached"]
                if ev == "RepairAll":
                    s["ship"]["hull"] = 1.0
            elif ev in ("RefuelAll", "RefuelPartial") and s["ship"].get("fuel_capacity"):
                if ev == "RefuelAll":
                    s["fuel"]["main"] = s["ship"]["fuel_capacity"]
                out = "status"
            if ev in FIX_EVENTS:
                fx = self._fix_from(e, ts)
                if fx:
                    s["last_fix"] = fx
                    out = out or "status"
            if ev in SCAN_EVENTS:
                out = "scan"
        if out:
            self._emit(out, {"event": ev, "ts": ts,
                             "system_id64": self.state["system"].get("id64")})
        return out

    @staticmethod
    def _ship_target(e: Dict[str, Any], prev: Optional[Dict[str, Any]],
                     ts: Optional[float]) -> Optional[Dict[str, Any]]:
        """ShipTargeted -> what the scan has revealed so far. The game sends
        one event per scan stage (0: ship, 1: pilot and rank, 2: shield and
        hull, 3: faction, legal state, bounty, subsystem); later stages of
        the same ship keep what earlier ones told."""
        if not e.get("TargetLocked"):
            return None
        ship_key = e.get("Ship")
        out: Dict[str, Any] = {}
        if prev and prev.get("ship_key") == ship_key and                 (e.get("PilotName") is None or prev.get("pilot_key") in (None, e.get("PilotName"))):
            out.update(prev)
        out.update({"ship_key": ship_key, "ts": ts,
                    "ship": e.get("Ship_Localised") or (ship_key or "").replace("_", " ").title(),
                    "stage": e.get("ScanStage")})
        for key, src in (("pilot", "PilotName_Localised"), ("pilot_key", "PilotName"),
                         ("rank", "PilotRank"), ("faction", "Faction"),
                         ("legal", "LegalStatus"), ("bounty", "Bounty"), ("power", "Power"),
                         ("squadron", "SquadronID")):
            if e.get(src) is not None:
                out[key] = e.get(src)
        if out.get("pilot") is None and out.get("pilot_key"):
            out["pilot"] = out["pilot_key"]
        for key, src in (("shield", "ShieldHealth"), ("hull", "HullHealth")):
            if e.get(src) is not None:
                out[key] = float(e.get(src)) / 100.0       # journal: 0..100
        if e.get("Subsystem"):
            out["subsystem"] = e.get("Subsystem_Localised") or e.get("Subsystem")
            out["subsystem_health"] = (float(e["SubsystemHealth"]) / 100.0
                                       if e.get("SubsystemHealth") is not None else None)
        return out

    def _fix_from(self, e: Dict[str, Any], ts: Optional[float]) -> Optional[Dict[str, Any]]:
        ev = e.get("event")
        sysid = e.get("SystemAddress") or self.state["system"].get("id64")
        if ev == "LeaveBody":
            # leaving a body keeps it as the last reference, just re-stamps it
            fx = self.state.get("last_fix")
            if fx and fx.get("body_id") == e.get("BodyID"):
                return dict(fx, event=ev, ts=ts)
            return None
        if ev == "ScanOrganic":
            bid = e.get("Body")
            return {"body": None, "body_id": bid if isinstance(bid, int) else None,
                    "system_id64": sysid, "event": ev, "ts": ts}
        name = e.get("Body") or e.get("BodyName")
        bid = e.get("BodyID")
        if name is None and bid is None:
            return None
        fx = {"body": name, "body_id": bid, "system_id64": sysid, "event": ev, "ts": ts}
        for k_src, k in (("Latitude", "lat"), ("Longitude", "lon")):
            if e.get(k_src) is not None:
                fx[k] = e.get(k_src)
        return fx

    @staticmethod
    def _hops(route: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"name": h.get("StarSystem"), "id64": h.get("SystemAddress"),
                 "pos": h.get("StarPos"), "star_class": h.get("StarClass")}
                for h in route]

    # ------------------------------------------------------------ status
    def feed_status(self, st: Dict[str, Any]) -> Optional[str]:
        """Apply a parsed Status.json."""
        if not st or st.get("event") != "Status":
            return None
        ts = parse_ts(st.get("timestamp"))
        with self._lock:
            s = self.state
            prev = s["status"]
            dest = st.get("Destination") or None
            new = {"ts": ts, "flags": int(st.get("Flags") or 0),
                   "flags2": int(st.get("Flags2") or 0),
                   "gui_focus": st.get("GuiFocus"),
                   "lat": st.get("Latitude"), "lon": st.get("Longitude"),
                   "alt": st.get("Altitude"), "heading": st.get("Heading"),
                   "body_name": st.get("BodyName"),
                   "radius": st.get("PlanetRadius"),
                   "destination": ({"system": dest.get("System"), "body": dest.get("Body"),
                                    "name": dest.get("Name_Localised") or dest.get("Name")}
                                   if dest else None),
                   "legal": st.get("LegalState"),
                   "pips": st.get("Pips"), "cargo": st.get("Cargo"),
                   "balance": st.get("Balance"), "fire_group": st.get("FireGroup"),
                   # on foot (Odyssey): suit oxygen and health 0..1, temperature K, gravity g
                   "oxygen": st.get("Oxygen"), "health": st.get("Health"),
                   "temp_k": st.get("Temperature"), "gravity": st.get("Gravity")}
            fuel = st.get("Fuel") or {}
            if fuel:
                s["fuel"]["main"] = fuel.get("FuelMain", s["fuel"].get("main"))
                s["fuel"]["reservoir"] = fuel.get("FuelReservoir", s["fuel"].get("reservoir"))
            s["status"] = new
            if new["body_name"] and new["lat"] is not None:
                fx = s.get("last_fix") or {}
                same = fx.get("body") == new["body_name"]
                s["last_fix"] = {"body": new["body_name"],
                                 "body_id": fx.get("body_id") if same else None,
                                 "system_id64": s["system"].get("id64"),
                                 "event": "Status", "ts": ts,
                                 "lat": new["lat"], "lon": new["lon"], "alt": new["alt"]}
            dest_changed = (prev.get("destination") != new["destination"])
        fx = self.state.get("last_fix") or {}
        self._emit("status", {"ts": ts, "gui_focus": new["gui_focus"], "flags": new["flags"],
                              "fuel": dict(self.state["fuel"]),
                              "fix": fx.get("body") or fx.get("body_id"),
                              # landed (Flags bit 1), in the SRV (bit 26) or on foot
                              # (Flags2 bit 0) with a position: the surface map applies
                              "on_surface": bool(new["lat"] is not None and (
                                  new["flags"] & 2 or new["flags"] & (1 << 26)
                                  or new["flags2"] & 1))})
        if dest_changed:
            self._emit("target", {"ts": ts, "destination": new["destination"]})
        return "status"

    # ------------------------------------------------------------- files
    @staticmethod
    def _sig(path: str) -> Optional[tuple]:
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    @staticmethod
    def _read_json(path: str) -> Optional[Dict[str, Any]]:
        # the game rewrites these files in place; a half-written read just
        # fails to parse and is retried on the next poll
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
            return json.loads(raw) if raw.strip() else None
        except (OSError, ValueError):
            return None

    def _read_status(self) -> None:
        path = os.path.join(self.journal_dir, "Status.json")
        sig = self._sig(path)
        if sig is None or sig == self._status_sig:
            return
        data = self._read_json(path)
        if data is None:
            return
        self._status_sig = sig
        self.feed_status(data)

    def _read_navroute(self, force: bool = False) -> None:
        path = os.path.join(self.journal_dir, "NavRoute.json")
        sig = self._sig(path)
        if sig is None or (sig == self._nav_sig and not force):
            return
        data = self._read_json(path)
        if data is None:
            return
        self._nav_sig = sig
        with self._lock:
            self.state["navroute"] = self._hops(data.get("Route") or [])
        self._emit("target", {"navroute": len(self.state["navroute"])})

    HEAD_BYTES = 160

    @classmethod
    def _head_of(cls, path: str) -> Optional[bytes]:
        """The file's first bytes - the Fileheader line with its timestamp."""
        try:
            with open(path, "rb") as fh:
                return fh.read(cls.HEAD_BYTES)
        except OSError:
            return None

    def _rewritten(self, path: str) -> bool:
        """The same journal file, but shorter than what we read or with
        another Fileheader: the game wrote it anew."""
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        head = self._head_of(path)
        if size < self._offset:
            return True
        if self._head and head and len(head) >= len(self._head) and head[:len(self._head)] != self._head:
            return True
        if head and (not self._head or len(head) > len(self._head)):
            self._head = head                 # remember it once it is complete
        return False

    def journals(self) -> List[str]:
        files = glob.glob(os.path.join(self.journal_dir, "Journal.*.log"))
        return sorted(files, key=lambda p: (os.path.getmtime(p), p))

    def _read_lines(self, path: str, start: int) -> int:
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                chunk = fh.read()
        except OSError:
            return start
        if not chunk:
            return start
        data = self._partial + chunk
        lines = data.split(b"\n")
        self._partial = lines.pop()            # incomplete last line
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                self.feed(json.loads(ln.decode("utf-8", "replace")))
            except ValueError:
                self.errors += 1
        return start + len(chunk)

    def prime(self, max_files: int = 4) -> None:
        """Read recent journals once (silently) to know where we are."""
        files = self.journals()
        if not files:
            return
        newest = files[-1]
        # a few older files first (oldest to newest) so the ship, the last
        # system and the fuel history are known even after a fresh start
        back = files[-max_files:]
        self._replaying = True
        try:
            for path in back[:-1]:
                self._partial = b""
                self._read_lines(path, 0)
            self._partial = b""
            self._offset = self._read_lines(newest, 0)
            self._file = newest
            self._head = self._head_of(newest)
        finally:
            self._replaying = False
        with self._lock:
            self.state["journal"] = os.path.basename(newest)
        self._read_navroute()
        self._read_status()

    def poll_once(self) -> None:
        files = self.journals()
        if files and files[-1] != self._file:
            self._file = files[-1]
            self._offset = 0
            self._partial = b""
            self._head = None
            with self._lock:
                self.state["journal"] = os.path.basename(self._file)
        if self._file:
            if self._offset and self._rewritten(self._file):
                # read the new content from its start, live
                self.rewrites += 1
                self._offset = 0
                self._partial = b""
                self._head = self._head_of(self._file)
            self._offset = self._read_lines(self._file, self._offset)
        self._read_status()
        self._read_navroute()
        self.last_poll = time.time()

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def restart(self) -> None:
        """Watchdog: the polling thread died - start a new one where it was."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="fis-live", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                self.errors += 1
            self._stop.wait(self.poll_s)

    def start(self) -> None:
        self.prime()
        self._thread = threading.Thread(target=self._run, name="fis-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
