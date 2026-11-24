# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
id64 as text where JavaScript would round it (5.1.0, re-audit 22.11.).

A system address has up to 55 bits; JavaScript numbers are exact only up to
2^53 - 1. Every whole number beyond that leaves the FIS as a string, so the
page compares, shows and sends back the exact id; everything smaller stays
a number (all ids seen so far are below 2^47 - nothing changes for them).
The page only compares and joins ids, never calculates with them.
"""
import json
from typing import Any

MAX_SAFE = 2 ** 53 - 1
# 2^53 has 16 digits; every id seen so far at most 15. Every digit mapped to
# "0", then one find for 16 of them: ~10 ms on 4 MB (a regex took ~110 ms)
_ZERO = str.maketrans("123456789", "000000000")
_RUN = "0" * 16


def dumps(obj: Any, **kw: Any) -> str:
    """json.dumps, with large ints as text. Fast path: the plain text holds no
    run of 16 digits, so no number can be too large - the structure is only
    walked (``safe``) when one is there."""
    text = json.dumps(obj, **kw)
    return json.dumps(safe(obj), **kw) if _RUN in text.translate(_ZERO) else text


def safe(obj: Any) -> Any:
    """``obj`` with every int beyond +-MAX_SAFE turned into its decimal text
    (bool stays bool); the same object when nothing needs changing."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return str(obj) if obj > MAX_SAFE or obj < -MAX_SAFE else obj
    if isinstance(obj, dict):
        out = None
        for k, v in obj.items():
            w = safe(v)
            if w is not v:
                if out is None:
                    out = dict(obj)
                out[k] = w
        return obj if out is None else out
    if isinstance(obj, (list, tuple)):
        items = [safe(v) for v in obj]
        return obj if all(a is b for a, b in zip(items, obj)) else items
    return obj


def as_id64(v: Any) -> Any:
    """An id64 the page sent back: an int, or the decimal text of one beyond
    MAX_SAFE (only those leave as text) -> int; anything else -> None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, str) and v.isdigit() and len(v) <= 20:
        n = int(v)
        return n if MAX_SAFE < n < 2 ** 64 else None
    return None
