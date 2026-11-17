# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
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
  SITUATION      (4.12, cockpitinfo / situation.py) in the opposite corner:
                 warnings, the landing card, the system's value, the session

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
MAX_INFO = 9              # 4.12: lines of the situation column

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


def _star_line(sc: str, scoop: Optional[bool]) -> Line:
    """STAR line of the briefing: class, and whether a fuel scoop works."""
    return ("STAR  %s%s" % (sc, "  scoopable" if scoop else
                            ("  NOT scoopable" if scoop is False else "")),
            COL["data"] if scoop or scoop is None else COL["warn"])


def _known_lines(info: Dict[str, Any]) -> List[Line]:
    """What the databases know of the place (shells.info_level)."""
    src = info.get("known_sources")
    level = info.get("level")
    if src:
        return [("KNOWN  %s" % ", ".join(src), COL["dim"])]
    if level == "inhabited":
        return [("INHABITED - known to the databases", COL["dim"])]
    if level == "unchecked":
        # I1: nobody was asked about this place - never claim "no database"
        return [("NOT CHECKED - outside our data frame", COL["dim"])]
    if level == "checked" or (level is None and src is not None):
        out = [("IN NO DATABASE - first discovery likely", COL["new"])]
        if info.get("checked_by"):
            out.append(("checked: %s" % ", ".join(info["checked_by"]), COL["dim"]))
        return out
    return []


def _lost_line(lost: Dict[str, Any]) -> Line:
    """Visited, yes - but what you did there went down with the ship."""
    bits = [b for b in ("%d scan" % lost["scan"] if lost.get("scan") else "",
                        "%d map" % lost["map"] if lost.get("map") else "",
                        "%d bio" % len(lost["bio"]) if lost.get("bio") else "") if b]
    return (("LOST IN CRASH  %s - redo" % ", ".join(bits))[:44], COL["alert"])


def briefing_lines(info: Dict[str, Any]) -> List[Line]:
    """
    BRIEFING block. info keys (all optional):
      name, kind ('target' | 'arrival'), star_class, scoopable (bool),
      known_sources (list of database names), visited (bool),
      boxel_open (int, open candidates in that boxel), jumps_left (int),
      fuel_warning (str), bodies (int), bodies_new (int),
      level ('known' | 'inhabited' | 'checked' | 'unchecked', shells.info_level),
      lost ({scan, map, bio} - data lost there in a crash, not redone yet),
      checked_by (list of sources that covered the position),
      region (codex region name)
    """
    name = info.get("name") or "?"
    kind = info.get("kind") or "target"
    head = "BRIEFING > %s" % name if kind == "target" else "ARRIVED > %s" % name
    out: List[Line] = [(head[:44], COL["head"])]
    sc = info.get("star_class")
    if sc:
        out.append(_star_line(sc, info.get("scoopable")))
    if info.get("region"):
        # 4.10: codex region (klightspeed's region map)
        out.append((("REGION  %s" % info["region"])[:44], COL["dim"]))
    out += _known_lines(info)
    if info.get("visited"):
        out.append(("visited before", COL["dim"]))
    lost = info.get("lost")
    if lost:
        out.append(_lost_line(lost))
    if info.get("also_by"):
        # C1: another commander on this PC has been there - your own
        # exploration is still open, the knowledge is shared
        out.append(("also explored by %s" % ", ".join(info["also_by"])[:26], COL["dim"]))
    if info.get("bodies"):
        nb = info.get("bodies_new") or 0
        out.append(("BODIES  %d%s" % (info["bodies"], ("  %d undiscovered" % nb) if nb else ""),
                    COL["new"] if nb else COL["data"]))
    if info.get("scoop"):
        # F1: where to scoop at the latest along the plotted route
        text, lvl = info["scoop"]
        out.append((text[:44], COL["alert"] if lvl == "alert" else
                    COL["warn"] if lvl == "warn" else COL["dim"]))
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
        self.mute_targets = False            # mining / on the ground: the route block steps aside
        self._mute_why: set = set()          # 4.12: why ("mining", "surface") - each lifts its own
        self._pending_brief: Optional[Tuple[List[Line], int, float]] = None
        self._targets_t = 0.0                # when the targets block was last sent
        self._last_state: List[Line] = []    # 5.0 (own-3): gear, lights, hardpoints
        self._state_t = 0.0

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
        """True when a drawing client is there (EDMCModernOverlay or the own
        window)."""
        return self._get() is not None

    @property
    def client(self) -> Any:
        """The drawing client in use (edmcoverlay's, or the plugin's own window)."""
        return self._client

    def use_client(self, client: Any) -> None:
        """D3 (4.12): draw through another client - the plugin's own window, or
        None to look for EDMCModernOverlay again. What is on screen is cleared."""
        self.clear()
        self._client = client
        self._tried = client is not None
        self._drawn = {}
        if self._last_targets and not self.mute_targets and not self.hidden:
            self.draw("targets", self._last_targets, ttl=self.TARGETS_TTL)

    # -- drawing -----------------------------------------------------------
    def _origin(self, group: str) -> Tuple[int, int]:
        x, y = ANCHORS.get(self.position, ANCHORS["top-left"])
        if group == "info":
            return self._info_origin()
        if group == "state":
            # 5.0 (own-3): always on the left, in the corner the other
            # blocks leave free (the bottom while they start at the top)
            corner = "bottom-left" if self.position.startswith("top") else "top-left"
            return ANCHORS[corner]
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
                if group == "mine" and self._drawn.get("nav"):
                    y += (self._drawn["nav"] + 1) * lh     # 4.12: below the compass (Rhino)
        return x, y

    def _info_origin(self) -> Tuple[int, int]:
        """4.12: the situation column - the corner across from the other
        blocks (left <-> right), so the two never cover each other."""
        side, _sep, edge = self.position.partition("-")
        other = "%s-%s" % (side, "right" if edge == "left" else "left")
        return ANCHORS.get(other, ANCHORS["top-right"])

    def draw(self, group: str, lines: Sequence[Line], ttl: int) -> bool:
        """Draw one block of lines at its place; lines left over from a longer
        block before are blanked. True when sent."""
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
        """Blank one block, or all blocks."""
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
        """The next targets of the in-system route; not drawn while muted or
        while a game screen hides the overlay."""
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

    STATE_TTL = 600         # s; sent again after half of it while unchanged

    def show_state(self, lines: Sequence[Line]) -> bool:
        """5.0 (own-3): what is still out (shipstate.reminder_lines) - drawn
        when it changes, blanked when nothing is out or a game screen is in
        front. True while it is on screen."""
        lines = list(lines)
        if self.hidden or not lines:
            if self._drawn.get("state"):
                self.clear("state")
            self._last_state = []
            return False
        now = time.time()
        if lines == self._last_state and self._drawn.get("state") and now - self._state_t < self.STATE_TTL / 2:
            return True
        if not self.draw("state", lines, ttl=self.STATE_TTL):
            return False
        self._last_state, self._state_t = lines, now
        return True

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

    def mute_route(self, on: bool, why: str = "mining") -> None:
        """While mining - and since 4.12 on the ground (landed, in the SRV,
        on foot) - the route targets are no help: hide them, bring them back
        when no reason is left. Each reason lifts only itself."""
        (self._mute_why.add if on else self._mute_why.discard)(why)
        on = bool(self._mute_why)
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

    def show_info(self, lines: Sequence[Line], seconds: int = 7) -> bool:
        """4.12: the situation column (cockpitinfo); not while a game screen
        is in front - the next tick draws it again."""
        if self.hidden:
            return False
        return self.draw("info", list(lines)[:MAX_INFO], ttl=seconds)

    def show_briefing(self, info: Dict[str, Any], seconds: int = 10) -> bool:
        """The briefing of a jump target; while a game screen hides the overlay
        only the newest is kept and drawn afterwards."""
        lines = briefing_lines(info)
        if self.hidden:
            # newest wins: picking several targets in the map shows only
            # the last one once you are back in the cockpit
            self._pending_brief = (lines, seconds, time.time())
            return False
        return self.draw("brief", lines, ttl=seconds)
