# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SHBOX FIS - flight information system, shipped with the SHBOXSEARCH plugin.

Reads only: the plugin database (read-only), the journal, Status.json,
NavRoute.json and the other state files the game writes. No input to the game,
no AI at runtime, Python standard library only.
"""

__version__ = "4.11.0"      # released together with the plugin

# The FIS reads EDMC's config.toml with tomllib: Python 3.11 or newer
MIN_PYTHON = (3, 11)


def python_problem(version=None) -> str:
    """Why this Python cannot run the FIS, or "" when it can."""
    import sys
    v = tuple((version or sys.version_info)[:2])
    if v >= MIN_PYTHON:
        return ""
    return ("SHBOX FIS needs Python %d.%d or newer (python.org) - this is Python %d.%d."
            % (MIN_PYTHON + v))
