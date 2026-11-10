# -*- coding: utf-8 -*-
"""
overlay.py - cockpit overlay for SHBOXSEARCH (optional)
=======================================================
Draws two small blocks over the game through EDMCModernOverlay (or the older
EDMCOverlay) using their common `edmcoverlay` API:

  NEXT TARGETS   the next stops of the in-system route, with distance and
                 what is to be done there - refreshed whenever the route
                 changes or a stop is ticked off
  BRIEFING       a few seconds after selecting a jump target and on arrival:
                 star class, scoopable, whether any database knows the system

Rules this module keeps:
  * it never raises - a missing or broken overlay must not touch the survey
  * it only DISPLAYS; nothing is sent to the game (Frontier's rules)
  * without an overlay plugin installed it does nothing at all

The overlay is a separate transparent window drawn by the overlay plugin on a
1280 x 960 virtual canvas; it is not part of the game's own rendering.

No EDMC imports here, so the text builders can be tested on their own.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Colour palette of the SHBOX display style
COL = {
    "head": "#3EF2E0",     # cyan - headings
    "data": "#7CFF6B",     # green - ordinary data
    "warn": "#FFB23E",     # amber - attention
    "alert": "#FF4D4D",    # red - fuel critical
    "new": "#B57CFF",      # violet - nobody has seen this yet
    "dim": "#8FA3A6",      # grey - secondary
}

# Top-left corner of each block on the 1280 x 960 canvas
ANCHORS: Dict[str, Tuple[int, int]] = {
    "top-left": (16, 96),
    "top-right": (900, 96),
    "bottom-left": (16, 690),
    "bottom-right": (900, 690),
}
POSITIONS = tuple(ANCHORS)
LINE_H = {"small": 16, "normal": 20}
BRIEFING_GAP = 8          # lines below the targets block where a briefing goes
MAX_LINES = 8
NAV_BELOW_BIO = 3         # the compass starts this many lines below the bio line

Line = Tuple[str, str]    # (text, colour)


# ---------------------------------------------------------------------------
# Text builders (pure)
# ---------------------------------------------------------------------------

def _stop_tasks(body: Any) -> str:
    out = []
    if getattr(body, "sig_bio", 0) and getattr(body, "organics", 0) < body.sig_bio:
        hint = getattr(body, "bio_hint", "") or ""
        out.append("BIO %d%s" % (body.sig_bio - body.organics,
                                 (" " + hint[:28]) if hint else ""))
    if getattr(body, "kind", "") == "Planet" and not getattr(body, "mapped", False):
        work = getattr(body, "work_label", None)
        label = work() if callable(work) else ""
        if "DSS" in (label or ""):
            out.append("DSS")
    if getattr(body, "was_discovered", None) == 0:
        out.append("NEW")
    return " ".join(out)


def targets_lines(route: Any, done: Iterable[int], limit: int = 3) -> List[Line]:
    """NEXT TARGETS block from a sysroute.SystemRoute."""
    if route is None or not getattr(route, "stops", None):
        return []
    done = set(done or ())
    left = [s for s in route.stops if s.body.body_id not in done]
    if not left:
        return [("SHBOX > %s" % (route.system or "system"), COL["head"]),
                ("all stops done", COL["data"])]
    out: List[Line] = [("SHBOX > NEXT TARGETS", COL["head"])]
    for i, s in enumerate(left[:limit], 1):
        name = (s.body.short or s.body.name or "?")[:18]
        tasks = _stop_tasks(s.body)
        colour = COL["new"] if getattr(s.body, "was_discovered", None) == 0 \
            else (COL["warn"] if "BIO" in tasks else COL["data"])
        out.append(("%d  %-18s %7.0f LS  %s" % (i, name, s.leg_ls, tasks), colour))
    rest_min = sum(s.leg_s + s.work_s for s in left) / 60.0
    out.append(("%d of %d left  ~%.0f min" % (len(left), len(route.stops), rest_min),
                COL["dim"]))
    return out


def briefing_lines(info: Dict[str, Any]) -> List[Line]:
    """
    BRIEFING block. info keys (all optional):
      name, kind ('target' | 'arrival'), star_class, scoopable (bool),
      known_sources (list of database names), visited (bool),
      boxel_open (int, open candidates in that boxel), jumps_left (int),
      fuel_warning (str), bodies (int), bodies_new (int)
    """
    name = info.get("name") or "?"
    kind = info.get("kind") or "target"
    head = "BRIEFING > %s" % name if kind == "target" else "ARRIVED > %s" % name
    out: List[Line] = [(head[:44], COL["head"])]
    sc = info.get("star_class")
    if sc:
        scoop = info.get("scoopable")
        out.append(("STAR  %s%s" % (sc, "  scoopable" if scoop else
                                    ("  NOT scoopable" if scoop is False else "")),
                    COL["data"] if scoop or scoop is None else COL["warn"]))
    src = info.get("known_sources")
    if src is not None:
        if src:
            out.append(("KNOWN  %s" % ", ".join(src), COL["dim"]))
        else:
            out.append(("IN NO DATABASE - first discovery likely", COL["new"]))
    if info.get("visited"):
        out.append(("visited before", COL["dim"]))
    if info.get("bodies"):
        nb = info.get("bodies_new") or 0
        out.append(("BODIES  %d%s" % (info["bodies"], ("  %d undiscovered" % nb) if nb else ""),
                    COL["new"] if nb else COL["data"]))
    if info.get("boxel_open"):
        out.append(("BOXEL  %d candidate%s still open" % (
            info["boxel_open"], "" if info["boxel_open"] == 1 else "s"), COL["warn"]))
    if info.get("fuel_warning"):
        out.append((info["fuel_warning"][:44], COL["alert"]))
    elif info.get("jumps_left") is not None:
        out.append(("FUEL  %d full-range jumps" % info["jumps_left"], COL["dim"]))
    return out[:MAX_LINES]


# ---------------------------------------------------------------------------
# Overlay client
# ---------------------------------------------------------------------------

class CockpitOverlay:
    """Thin, failure-proof wrapper around edmcoverlay.Overlay."""

    PREFIX = "shbox-"

    # Status.json GuiFocus values where the game shows its own full-screen
    # UI and the overlay would cover it: 5 station services, 6 galaxy map,
    # 7 system map, 8 orrery, 9 FSS, 10 SAA (DSS), 11 codex.
    # 0 cockpit and 1-4 (side panels, comms, role panel) keep it visible.
    HIDE_FOCUS = frozenset({5, 6, 7, 8, 9, 10, 11})
    BRIEF_KEEP = 300        # a held-back briefing is shown up to 5 min later
    TARGETS_TTL = 900       # s the overlay keeps the targets block on screen
    TARGETS_REFRESH = 300   # s: sent again well before that runs out

    def __init__(self, log: Optional[logging.Logger] = None, client: Any = None):
        self.log = log or logger
        self._client = client
        self._tried = client is not None
        self._drawn: Dict[str, int] = {}     # group -> number of lines on screen
        self.enabled = True
        self.position = "top-left"
        self.size = "small"
        self.hidden = False                  # a game screen is in front
        self._last_targets: List[Line] = []
        self.mute_targets = False            # mining: the route block steps aside
        self._pending_brief: Optional[Tuple[List[Line], int, float]] = None
        self._targets_t = 0.0                # when the targets block was last sent

    # -- game screens ------------------------------------------------------
    def set_focus(self, focus: Optional[int]) -> None:
        """
        Follow Status.json GuiFocus. Selecting a jump target happens in the
        galaxy map, so a briefing drawn right away lands on top of the map's
        own system panel. While such a screen is open everything is held back
        and drawn again on the way back to the cockpit - the briefing then
        appears exactly when you look out of the canopy again.
        """
        try:
            hide = int(focus or 0) in self.HIDE_FOCUS
        except (TypeError, ValueError):
            hide = False
        if hide == self.hidden:
            return
        self.hidden = hide
        if hide:
            self.clear()
            return
        if self._last_targets and not self.mute_targets:
            self.draw("targets", self._last_targets, ttl=self.TARGETS_TTL)
        pb = self._pending_brief
        self._pending_brief = None
        if pb and time.time() - pb[2] <= self.BRIEF_KEEP:
            self.draw("brief", pb[0], ttl=pb[1])

    # -- connection --------------------------------------------------------
    def _get(self):
        if self._client is not None:
            return self._client
        if self._tried:
            return None
        self._tried = True
        try:
            import edmcoverlay  # provided by EDMCModernOverlay / EDMCOverlay
            self._client = edmcoverlay.Overlay()
            self.log.info("overlay | connected (%s)", getattr(
                edmcoverlay, "MODERN_OVERLAY_IDENTITY", {}).get("plugin", "edmcoverlay"))
        except Exception as e:
            self._client = None
            self.log.info("overlay | no overlay plugin available (%s)", e)
        return self._client

    def available(self) -> bool:
        return self._get() is not None

    # -- drawing -----------------------------------------------------------
    def _origin(self, group: str) -> Tuple[int, int]:
        x, y = ANCHORS.get(self.position, ANCHORS["top-left"])
        if group in ("brief", "bio", "nav", "mine"):
            lh = LINE_H.get(self.size, 16)
            down = (self._drawn.get("targets", 0) + 1) * lh
            if self.position.startswith("bottom"):
                y -= (MAX_LINES + 1) * lh          # briefing above the targets
                if group in ("nav", "mine"):
                    y -= (MAX_LINES + 1) * lh
            else:
                y += max(down, BRIEFING_GAP * lh // 2)
                if group in ("nav", "mine"):
                    y += NAV_BELOW_BIO * lh        # room for the bio distance line
        return x, y

    def draw(self, group: str, lines: Sequence[Line], ttl: int) -> bool:
        if not self.enabled:
            return False
        c = self._get()
        if c is None:
            return False
        x, y = self._origin(group)
        lh = LINE_H.get(self.size, 16)
        try:
            for i, (text, colour) in enumerate(lines):
                c.send_message("%s%s-%d" % (self.PREFIX, group, i), text, colour,
                               x, y + i * lh, ttl=ttl, size=self.size)
            # blank whatever is left over from a longer previous block
            for i in range(len(lines), self._drawn.get(group, 0)):
                c.send_message("%s%s-%d" % (self.PREFIX, group, i), "", COL["dim"],
                               x, y + i * lh, ttl=1, size=self.size)
            self._drawn[group] = len(lines)
            if group == "targets":
                self._targets_t = time.time()
            return True
        except Exception as e:
            self.log.debug("overlay | draw %s failed: %s", group, e)
            return False

    def clear(self, group: Optional[str] = None) -> None:
        c = self._client
        if c is None:
            return
        groups = [group] if group else list(self._drawn)
        for g in groups:
            for i in range(self._drawn.get(g, 0)):
                try:
                    c.send_message("%s%s-%d" % (self.PREFIX, g, i), "", COL["dim"],
                                   0, 0, ttl=1, size=self.size)
                except Exception:
                    pass
            self._drawn[g] = 0

    # -- the two blocks ----------------------------------------------------
    def show_targets(self, route: Any, done: Iterable[int]) -> bool:
        lines = targets_lines(route, done)
        self._last_targets = lines
        if self.mute_targets:
            self.clear("targets")
            return False
        if not lines:
            self.clear("targets")
            return False
        if self.hidden:
            return False                     # drawn when the screen closes
        return self.draw("targets", lines, ttl=self.TARGETS_TTL)

    def keep_targets(self, now: Optional[float] = None) -> bool:
        """
        Send the targets block again before its time on screen runs out.
        Only a route change redraws it otherwise, so on a long supercruise
        leg, on foot or in the SRV it vanished after 15 minutes.
        """
        now = time.time() if now is None else now
        if (self.mute_targets or self.hidden or not self._last_targets
                or now - self._targets_t < self.TARGETS_REFRESH):
            return False
        return self.draw("targets", self._last_targets, ttl=self.TARGETS_TTL)

    def show_bio(self, lines: Sequence[Line], seconds: int = 8) -> bool:
        """Exobiology distance line while sampling; held back like a briefing."""
        if self.hidden:
            return False
        return self.draw("bio", list(lines), ttl=seconds)

    def show_nav(self, lines: Sequence[Line], seconds: int = 4) -> bool:
        """Surface compass; refreshed every second while a position exists."""
        if self.hidden:
            return False
        return self.draw("nav", list(lines), ttl=seconds)

    def mute_route(self, on: bool) -> None:
        """While mining the route targets are no help: hide them, bring them
        back afterwards."""
        if on == self.mute_targets:
            return
        self.mute_targets = on
        if on:
            self.clear("targets")
        elif self._last_targets and not self.hidden:
            self.draw("targets", self._last_targets, ttl=self.TARGETS_TTL)

    def show_mining(self, lines: Sequence[Line], seconds: int = 30) -> bool:
        """Mining block (miningstat): at most five lines, while you mine."""
        if self.hidden:
            return False
        return self.draw("mine", list(lines)[:5], ttl=seconds)

    def show_briefing(self, info: Dict[str, Any], seconds: int = 10) -> bool:
        lines = briefing_lines(info)
        if self.hidden:
            # newest wins: picking several targets in the map shows only
            # the last one once you are back in the cockpit
            self._pending_brief = (lines, seconds, time.time())
            return False
        return self.draw("brief", lines, ttl=seconds)


def _selftest() -> int:
    """python overlay.py - the targets block stays on screen (fake client)."""
    sent: List[Tuple[str, str, int]] = []

    class Client:
        def send_message(self, mid, text, colour, x, y, ttl=4, size="normal"):
            sent.append((mid, text, ttl))

    ov = CockpitOverlay(client=Client())
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    ov._last_targets = [("NEXT TARGETS", COL["head"]), ("1. A 2  DSS", COL["data"])]
    t0 = 1000.0
    ov._targets_t = t0
    check(not ov.keep_targets(t0 + 60), "fresh block is left alone")
    check(ov.keep_targets(t0 + ov.TARGETS_REFRESH + 1) and sent[-1][2] == ov.TARGETS_TTL,
          "sent again before its time on screen runs out")
    n = len(sent)
    ov.hidden = True
    check(not ov.keep_targets(ov._targets_t + 9999) and len(sent) == n, "not over a map screen")
    ov.hidden, ov.mute_targets = False, True
    check(not ov.keep_targets(ov._targets_t + 9999), "not while mining")
    ov.mute_targets, ov._last_targets = False, []
    check(not ov.keep_targets(ov._targets_t + 9999), "nothing to keep")
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
