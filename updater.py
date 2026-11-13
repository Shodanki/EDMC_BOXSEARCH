# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The update check against the GitHub releases API.

One request per day at most, through netgate's gateway, only when the
user ticked it. Compares SemVer versions (a pre-release is older than its
release) and offers the release page.
"""

from __future__ import annotations

import re
import time
from typing import Tuple

from .state import CFG, RELEASES_API, RELEASES_URL, REPO_URL, ST, VERSION, cfg_bool, cfg_set, cfg_str, logger
from . import panel
from . import planning
from . import survey
from . import uithread


def _version_tuple(v: str) -> Tuple[int, ...]:
    """'v4.1.0' -> (4, 1, 0). Anything unparseable sorts lowest. Only the
    leading digits of a part count: '5.0.0-beta1' is (5, 0, 0), not newer
    than 5.0.0 (up to 5.0 the digits of 'beta1' made it (5, 0, 1))."""
    parts = []
    for chunk in (v or "").lstrip("vV").split(".")[:4]:
        m = re.match(r"\s*(\d+)", chunk)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) or (0,)


def _check_for_update(force: bool = False) -> None:
    """
    Ask GitHub whether a newer release exists. Notify only - never touch files.

    The plugin is deliberately not self-updating: its value sits in a database
    that grows over months, and a half-applied update in the same folder is
    the one failure that is genuinely painful. Copying eight files by hand a
    few times a year is the better trade.

    Checked once a day at most. GitHub allows 60 unauthenticated calls per
    hour per address, and every failure is swallowed - an update check must
    never be the reason something does not work.
    """
    # Every way out says why, at INFO: in 4.0 the check left no trace at all
    # in the log, so nobody could tell whether it ran, failed or was off.
    if not force and not cfg_bool(CFG["check_updates"], True):
        logger.info("update check: switched off in the preferences")
        return
    if not force:
        last = cfg_str(CFG["update_checked"], "")
        try:
            if last and time.time() - float(last) < 86400:
                logger.info("update check: last run %.1f h ago, next after 24 h",
                            (time.time() - float(last)) / 3600.0)
                return
        except ValueError:
            pass
    if not ST.net.usable:
        logger.info("update check: 'requests' not available in this EDMC build")
        return
    try:
        r = ST.net.request("github", "GET", RELEASES_API, "releases/latest",
                           timeout=10,
                           headers={"Accept": "application/vnd.github+json"})
        planning._flush_net_log()
        if r is None:
            logger.info("update check: no answer (offline, resting or no network)")
            return
        cfg_set(CFG["update_checked"], str(int(time.time())))
        if r.status_code == 403:
            logger.info("update check: rate limited by GitHub, trying again tomorrow")
            return
        if r.status_code == 404:
            logger.info("update check: no release published yet")
            return
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.info("update check failed (ignored): %s", e)
        return

    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return
    if _version_tuple(tag) <= _version_tuple(VERSION):
        logger.info("update check: %s is current (latest %s)", VERSION, tag)
        if force:
            panel._set_status("up to date (%s)" % VERSION)
        return

    ST.update_version = tag
    ST.update_notes = (data.get("body") or "").strip()
    logger.info("update available: %s (running %s) - %s", tag, VERSION,
                RELEASES_URL)
    for line in ST.update_notes.splitlines()[:8]:
        logger.info("update | %s", line)
    panel._set_status("update %s available - click here" % tag)
    uithread._ui(panel._refresh)


def _open_release_page() -> None:
    """Open the release page; the copying stays with the commander."""
    import webbrowser
    try:
        webbrowser.open(RELEASES_URL if ST.update_version else REPO_URL)
        if ST.update_version:
            cfg_set(CFG["update_seen"], ST.update_version)
    except Exception:
        logger.exception("could not open the browser")
        survey._copy(RELEASES_URL)
