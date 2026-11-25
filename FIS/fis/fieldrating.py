# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
MP3 (5.1.0, user 24.11.): the mining fields rated - purity, prospectors per
good rock, by-catch, against the commander's own average. The counting lives
in the plugin's miningfields.py (SP2: the overlay counts the same way); here
the FIS's own mining sessions (mining._runs) cut the journal.
"""
from typing import Any, Dict, Iterable, List

from .model import _optional


def rate_fields(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """MP3: one row per mining field (ring + material looked for), the best
    first; none with a plugin older than 5.1.0."""
    mf = _optional("miningfields")
    if mf is None:
        return []
    from .mining import _runs
    return mf.rate_fields(events, split=_runs)
