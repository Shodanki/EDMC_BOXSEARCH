# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Maintenance: journal import, first-run migration, upgrade replays,
import and export of survey data."""

from __future__ import annotations

import os
import time
from tkinter import filedialog
from typing import Optional

# EDMC API
from config import config

from .boxelplan import Planner
from .sysdb import CMDR_READY, LOSS_REPLAY
from .state import CFG, ST, _PLUGIN_DIR, cfg_bool, cfg_int, get_masscodes, logger
from . import panel
from . import planning
from . import routewin


def _journal_dir() -> Optional[str]:
    """Journal folder: EDMC's own setting first, then the default paths."""
    for getter in ("get_str", "get"):
        try:
            v = getattr(config, getter)("journaldir")
            if v and os.path.isdir(v):
                return v
        except Exception:
            pass
    for attr in ("default_journal_dir", "default_journal_dir_path"):
        try:
            v = getattr(config, attr, None)
            if callable(v):
                v = v()
            if v and os.path.isdir(str(v)):
                return str(v)
        except Exception:
            pass
    for p in (r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous",
              r"%HOMEPATH%\Saved Games\Frontier Developments\Elite Dangerous"):
        q = os.path.expandvars(p)
        if os.path.isdir(q):
            return q
    return None


def _import_journals(max_files: int = 0) -> None:
    d = _journal_dir()
    if not d:
        panel._set_status("journal folder not found")
        logger.warning("journal folder not found")
        return

    def prog(i, total, fn):
        panel._set_status("journals %d/%d" % (i, total))

    # the lock is taken per chunk inside, never for the whole replay
    res = ST.db.import_journals(d, max_files=max_files, progress=prog, lock=ST.lock)
    logger.info("journals replayed: %s", res)
    panel._set_status("journals: %d files, %d lines, %d events"
                      % (res["files"], res["lines"], res["events"]))
    if ST.active:
        planning._rebuild_plan()


def _first_run_migration() -> None:
    """
    Runs once on first start (it replaced the 4.0 script migrate.py), so no system-wide
    Python installation is needed - EDMC ships its own interpreter.
    """
    logger.info("first-run import starting")
    panel._set_status("first-run import: JSON")
    _import_json()
    panel._set_status("first-run import: journals")
    _import_journals()
    with ST.lock:
        st = ST.db.stats()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ST.db.set_meta("migrated", now)
        for t in REPLAY_TAGS:                 # a fresh import already has it all
            ST.db.set_meta(t, now)
    logger.info("first-run import finished: %s", st)
    planning._apply_main_cmdr()
    routewin._rebuild_route()
    panel._set_status("first-run import done: %d systems, %d bodies"
                      % (st["systems"], st["bodies"]))


# Releases that need one full journal replay to fill what they store new.
# upgrade_44b: barycentre parents (binary moons placed far from their planet)
# upgrade_46_rigs: Rhino rig collection points from MiningRefined + the track
# upgrade_48_cmdr (C1): exploration per commander - visited, FSS, scans,
# maps, first discoveries and species analysed sorted by FID
# upgrade_48_lost: what each commander carries unsold, and what a lost ship
# took with it (marked, planned again)
REPLAY_TAGS = ("upgrade_41", "upgrade_43", "upgrade_44", "upgrade_44b",
               "upgrade_46_rigs", CMDR_READY, LOSS_REPLAY)


def _upgrade_replay() -> None:
    """
    One full journal replay after an update that stores something new.

    4.3: the signal atlas (planetary mining locations, geological and
    biological signals, genera incl. Brain Trees, codex sites) and the
    material atlas (where each material was picked up).

    4.1:
    * fills the new per-body columns (gravity, temperature, atmosphere,
      volcanism, materials, radius, rings ...) from the existing history
    * corrects the bio sample counter: up to 4.0 every replay - including
      the automatic one behind the route window - added +1 per sample again,
      so bodies looked sampled when they were not. It is now written as the
      number of distinct species analysed, so this replay sets it right.
    """
    # let EDMC finish its own start-up (journal monitor, commander, cAPI) first
    time.sleep(15)
    todo = [t for t in REPLAY_TAGS if not ST.db.get_meta(t)]
    logger.info("upgrade (%s): replaying all journals once to fill new data",
                ", ".join(todo))
    panel._set_status("upgrade: journals")
    _import_journals()
    with ST.lock:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for t in todo:
            ST.db.set_meta(t, now)
        n_sig = len(ST.db.signal_kinds())
        n_mat = len(ST.db.material_kinds())
        n_cmdr = len(ST.db.commanders())
    logger.info("upgrade finished - atlas: %d signal kinds, %d materials, "
                "%d commanders", n_sig, n_mat, n_cmdr)
    planning._apply_main_cmdr()
    routewin._rebuild_route()


def _selftest() -> None:
    """Verify the procgen maths. Result goes to the EDMC log."""
    import io
    import contextlib
    import procgen
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fails = procgen._selftest()
    for line in buf.getvalue().splitlines():
        logger.info("selftest | %s", line)
    with ST.lock:
        st = ST.db.stats()
    logger.info("selftest | database: %s", st)
    panel._set_status("self test: %s (details in log)"
                      % ("passed" if fails == 0 else "%d failures" % fails))


def _import_json() -> None:
    ok_total = 0
    for fn, fn2 in (("neareststars.json", "import_neareststars"),
                    ("survey_state.json", "import_survey_state")):
        p = os.path.join(_PLUGIN_DIR, fn)
        if os.path.exists(p):
            with ST.lock:
                a, b = getattr(ST.db, fn2)(p)
            ok_total += a
            logger.info("%s -> %d / %d", fn, a, b)
    panel._set_status("JSON import: %d records" % ok_total)


def _export_csv() -> None:
    if not (ST.center and ST.planner):
        panel._set_status("no active survey")
        return
    p = filedialog.asksaveasfilename(defaultextension=".csv",
                                     initialfile="shboxsearch_plan.csv")
    if not p:
        return
    with ST.lock:
        plan = ST.planner.build(ST.center, planning._plan_radius(), masscodes=get_masscodes(),
                                probe_depth=cfg_int(CFG["probe_depth"], 2),
                                include_empty=cfg_bool(CFG["include_empty"], True))
    n = Planner.export_csv(plan, p)
    panel._set_status("%d targets written to %s" % (n, os.path.basename(p)))


def _export_prefixes() -> None:
    if not (ST.center and ST.planner):
        panel._set_status("no active survey")
        return
    p = filedialog.asksaveasfilename(defaultextension=".txt",
                                     initialfile="boxel_praefixe.txt")
    if not p:
        return
    with ST.lock:
        plan = ST.planner.build(ST.center, planning._plan_radius(), masscodes=get_masscodes(),
                                probe_depth=cfg_int(CFG["probe_depth"], 2),
                                include_empty=cfg_bool(CFG["include_empty"], True))
    rows = Planner.boxel_prefixes(plan, limit=100000)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# One prefix per boxel. Paste into the galaxy map search;\n"
                "# the result list shows every system of that boxel.\n")
        for pref, d, n in rows:
            f.write("%-32s  %7.1f ly  open %d\n" % (pref, d, n))
    panel._set_status("%d prefixes written to %s" % (len(rows), os.path.basename(p)))
