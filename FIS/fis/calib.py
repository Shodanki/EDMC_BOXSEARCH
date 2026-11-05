"""Cost model calibrated from the commander's own journals.

The plugin measures its route times live (supercruise segments and the time
a surface scan or a biological sample takes) and bootstraps the work part
from the last 30 journals at start-up. That code lives in the plugin's
`load.py`, which needs EDMC, so the FIS repeats only the *measuring* here and
leaves the *fitting* to the plugin's own `sysroute.calibrate_*` functions -
the numbers therefore come out the way the plugin would compute them.

Read-only: journals are opened for reading, the database is only queried.
"""

from __future__ import annotations

import glob
import json
import os
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

LegLookup = Callable[[int, Optional[int], Optional[str]], Optional[float]]


class Measurements:
    def __init__(self) -> None:
        self.dss: List[float] = []
        self.bio: List[float] = []
        self.sc: List[Tuple[float, float]] = []   # (arrival_ls, seconds)
        self.events = 0
        self.files = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"dss": len(self.dss), "bio": len(self.bio), "sc": len(self.sc),
                "events": self.events, "files": self.files}


LegLookup = Callable[[int, str, str, float], Optional[float]]


def measure(events: Iterable[Dict[str, Any]], leg: Optional[LegLookup] = None,
            m: Optional[Measurements] = None) -> Measurements:
    """Collect clean timing intervals, same brackets as plugin 4.3:

    * DSS: arrival at the body (ApproachBody/SupercruiseExit) -> SAAScanComplete,
      otherwise the gap between consecutive mappings in one system.
    * Bio: first Log/Sample of a species -> its Analyse.
    * Supercruise: body A -> body B inside one system (SupercruiseEntry near
      the body you were last at, SupercruiseExit at the next one); the
      distance comes from `leg(system, A, B, unix time)`, i.e. from the
      orbits at the time of the flight. The first leg after a jump is NOT
      used: it also holds honk/FSS on arrival (measured 05.11.: fastest
      first legs 190-270 s almost independent of distance).
    """
    m = m or Measurements()
    arrive: Dict[str, float] = {}
    blog: Dict[Tuple, float] = {}
    last_saa: Dict[Any, float] = {}
    here: Dict[str, Any] = {"sys": None, "body": None}
    sc_from: Optional[Tuple[Any, str, float]] = None
    for e in events:
        ts = parse_ts(e.get("timestamp"))
        if ts is None:
            continue
        m.events += 1
        v = e.get("event")
        if v in ("ApproachBody", "SupercruiseExit") and e.get("Body"):
            arrive[e["Body"]] = ts
        if v in ("FSDJump", "CarrierJump", "Location"):
            here = {"sys": e.get("SystemAddress"), "body": None}
            sc_from = None
        elif v == "SupercruiseEntry":
            sc_from = (here["sys"], here["body"], ts) if here["sys"] and here["body"] else None
        elif v == "SupercruiseExit":
            body = e.get("Body")
            if (sc_from and body and body != sc_from[1] and leg is not None
                    and e.get("SystemAddress") == sc_from[0] and 5 < ts - sc_from[2] < 3600):
                d = leg(int(sc_from[0]), sc_from[1], body, sc_from[2])
                if d and d > 1.0:
                    m.sc.append((float(d), ts - sc_from[2]))
            sc_from = None
            if body and e.get("SystemAddress"):
                here = {"sys": e["SystemAddress"], "body": body}
        elif v in ("Touchdown", "Liftoff") and e.get("Body"):
            here = {"sys": e.get("SystemAddress") or here["sys"], "body": e["Body"]}
        elif v in ("Shutdown", "LoadGame", "Died", "Resurrect"):
            sc_from = None
        if v == "SAAScanComplete":
            t0 = arrive.pop(e.get("BodyName"), None)
            prev = last_saa.get(e.get("SystemAddress"))
            if t0 and 10 < ts - t0 < 1800:
                m.dss.append(ts - t0)
            elif prev and 20 < ts - prev < 1800:
                m.dss.append(ts - prev)
            last_saa[e.get("SystemAddress")] = ts
        elif v == "ScanOrganic":
            key = (e.get("SystemAddress"), e.get("Body"), e.get("Species"))
            kind = e.get("ScanType")
            if kind in ("Log", "Sample"):
                blog.setdefault(key, ts)
            elif kind == "Analyse":
                t0 = blog.pop(key, None)
                if t0 and 20 < ts - t0 < 3600:
                    m.bio.append(ts - t0)
    return m


def journal_files(journal_dir: str, limit: int = 30) -> List[str]:
    files = glob.glob(os.path.join(journal_dir, "Journal.*.log")) + \
        glob.glob(os.path.join(journal_dir, "Journal_*.log"))
    return sorted(files)[-limit:]


def read_events(paths: Iterable[str]) -> Iterable[Dict[str, Any]]:
    for fn in paths:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except OSError:
            continue


def fit(sysroute: Any, m: Measurements) -> Any:
    """Plugin's own fitting: travel part first, then the work part."""
    model = sysroute.calibrate_from_journal(m.sc, sysroute.DEFAULT_MODEL)
    return sysroute.calibrate_work_from_journal(m.dss, m.bio, [], model)


def fit_like_plugin(sysroute: Any, m: Measurements) -> Any:
    """What the plugin has right after start-up: default travel model, work
    part from the journals. Used for the ORDER of the stops (2-opt weighs
    legs with the model), so the FIS keeps the plugin's order."""
    return sysroute.calibrate_work_from_journal(m.dss, m.bio, [], sysroute.DEFAULT_MODEL)


class Calibrator:
    """Holds the current model; re-measures when the journals changed,
    at most every `min_interval` seconds, on a background thread."""

    def __init__(self, journal_dir: str, sysroute: Any,
                 leg: Optional[LegLookup] = None,
                 files: int = 30, min_interval: float = 600.0) -> None:
        self.journal_dir = journal_dir
        self.sysroute = sysroute
        self.leg = leg
        self.files = files
        self.min_interval = min_interval
        self.model = sysroute.DEFAULT_MODEL         # times shown
        self.order_model = sysroute.DEFAULT_MODEL   # order of the stops
        self.info: Dict[str, Any] = {"calibrated": False}
        self._sig: Any = None
        self._last = time.time()   # first measurement: run_once() at start-up
        self._lock = threading.Lock()
        self._busy = False

    def _signature(self, paths: List[str]) -> Any:
        try:
            return tuple((p, os.path.getsize(p)) for p in paths[-2:])
        except OSError:
            return None

    def run_once(self) -> Any:
        paths = journal_files(self.journal_dir, self.files)
        sig = self._signature(paths)
        m = Measurements()
        m.files = len(paths)
        measure(read_events(paths), self.leg, m)
        model = fit(self.sysroute, m)
        order = fit_like_plugin(self.sysroute, m)
        info = {"calibrated": model is not self.sysroute.DEFAULT_MODEL,
                "measured": m.as_dict(), "model": model.as_dict(),
                "order_model": order.as_dict(), "ts": time.time()}
        with self._lock:
            self.model, self.order_model = model, order
            self.info, self._sig, self._last = info, sig, time.time()
        return model

    def maybe_refresh(self) -> None:
        """Cheap check; starts a background re-measure when due."""
        now = time.time()
        if self._busy or now - self._last < self.min_interval:
            return
        paths = journal_files(self.journal_dir, self.files)
        if self._signature(paths) == self._sig:
            self._last = now
            return
        self._busy = True

        def work() -> None:
            try:
                self.run_once()
            except Exception:
                pass
            finally:
                self._busy = False
        threading.Thread(target=work, name="fis-calib", daemon=True).start()
