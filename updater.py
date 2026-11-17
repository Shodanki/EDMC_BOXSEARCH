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
from typing import Any, Dict, Optional, Tuple

from .state import CFG, RELEASES_API, RELEASES_URL, REPO_URL, ST, VERSION, cfg_bool, cfg_set, cfg_str, logger
from . import panel
from . import planning
from . import survey
from . import uithread


def _version_tuple(v: str) -> Tuple[Any, ...]:
    """
    A sort key for a version after SemVer 2.0.0: 'v4.1.0' -> (4, 1, 0, 1).

    A pre-release sorts before its release: '5.0.0-beta1' < '5.0.0' (up to
    4.12 both were (5, 0, 0), so a beta running saw the final release as
    "current"). Pre-release identifiers compare one by one, numbers as
    numbers and below words ('beta.2' < 'beta.11' < 'rc.1'). Build metadata
    after '+' is ignored. Only the leading digits of a core part count, a
    missing part is 0 ('4.1' == '4.1.0'), anything unparseable sorts lowest.
    """
    text = (v or "").strip().lstrip("vV").split("+", 1)[0]
    core, _, pre = text.partition("-")
    parts = []
    for chunk in core.split(".")[:3]:
        m = re.match(r"\s*(\d+)", chunk)
        parts.append(int(m.group(1)) if m else 0)
    if not any(re.match(r"\s*\d", c) for c in core.split(".")):
        return (0,)
    parts += [0] * (3 - len(parts))
    if not pre:
        return tuple(parts) + (1,)
    return tuple(parts) + (0,) + _pre_release_key(pre)


def _pre_release_key(pre: str) -> Tuple[Tuple[int, Any], ...]:
    """SemVer pre-release identifiers as comparable pairs: a number (0, n)
    sorts below a word (1, 'beta'); a shorter list of equal identifiers
    sorts first."""
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split("."))


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
    if not _update_due(force):
        return
    data = _latest_release()
    if data is None:
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


def _update_due(force: bool) -> bool:
    """Whether to ask now: switched on, and the last check 24 h ago (both
    skipped with force), and requests usable. Every way out says why, at
    INFO: in 4.0 the check left no trace at all in the log, so nobody could
    tell whether it ran, failed or was off."""
    if not force and not cfg_bool(CFG["check_updates"], True):
        logger.info("update check: switched off in the preferences")
        return False
    if not force:
        last = cfg_str(CFG["update_checked"], "")
        try:
            if last and time.time() - float(last) < 86400:
                logger.info("update check: last run %.1f h ago, next after 24 h",
                            (time.time() - float(last)) / 3600.0)
                return False
        except ValueError:
            pass
    if not ST.net.usable:
        logger.info("update check: 'requests' not available in this EDMC build")
        return False
    return True


def _latest_release() -> Optional[Dict[str, Any]]:
    """The latest release from the GitHub API, through the gateway; None
    when there is no usable answer (offline, resting, rate limited, none
    published, an error - all logged and swallowed)."""
    try:
        r = ST.net.request("github", "GET", RELEASES_API, "releases/latest",
                           timeout=10,
                           headers={"Accept": "application/vnd.github+json"})
        planning._flush_net_log()
        if r is None:
            logger.info("update check: no answer (offline, resting or no network)")
            return None
        cfg_set(CFG["update_checked"], str(int(time.time())))
        if r.status_code == 403:
            logger.info("update check: rate limited by GitHub, trying again tomorrow")
            return None
        if r.status_code == 404:
            logger.info("update check: no release published yet")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.info("update check failed (ignored): %s", e)
        return None


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
