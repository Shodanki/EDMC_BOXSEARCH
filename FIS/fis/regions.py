# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SC3 (5.1.0, StellarCartography idea): the 42 codex regions as outlines in
GALAXY - from the region map the plugin already carries (regionmap, MIT,
Ben Peddell), looked up on the galactic plane every STEP light years. Built
once per FIS run (0.2 s), sent run-length coded; nothing new is read or
fetched.
"""
from typing import Any, Callable, Dict, List, Optional, Sequence

STEP = 250                     # ly between two looked-up points
X0, X1 = -45000, 45000
Z0, Z1 = -25000, 75000

_CACHE: Dict[str, Any] = {}


def build(find_region: Callable[[float, float, float], Any], names: Sequence[str]) -> Dict[str, Any]:
    """{"step", "x0", "z0", "w", "h", "rows" (per z row: [id, run, id, run ...]),
    "names" (id -> name), "labels" ([id, x, z] at each region's middle)}."""
    w, h = (X1 - X0) // STEP + 1, (Z1 - Z0) // STEP + 1
    rows: List[List[int]] = []
    sums: Dict[int, List[float]] = {}
    for j in range(h):
        z = Z0 + j * STEP
        row: List[int] = []
        last: Optional[int] = None
        for i in range(w):
            x = X0 + i * STEP
            r = find_region(x, 0.0, z)
            rid = int(r[0]) if r else 0
            if rid:
                s = sums.setdefault(rid, [0.0, 0.0, 0])
                s[0] += x
                s[1] += z
                s[2] += 1
            if rid == last:
                row[-1] += 1
            else:
                row += [rid, 1]
                last = rid
        rows.append(row)
    labels = [[rid, round(s[0] / s[2]), round(s[1] / s[2])] for rid, s in sorted(sums.items())]
    return {"step": STEP, "x0": X0, "z0": Z0, "w": w, "h": h, "rows": rows,
            "names": {str(i + 1): n for i, n in enumerate(names)}, "labels": labels}


def cached(regionmap: Any) -> Optional[Dict[str, Any]]:
    """The outlines, built once; None without a region map."""
    if regionmap is None:
        return None
    if "v" not in _CACHE:
        _CACHE["v"] = build(regionmap.find_region, regionmap.region_names())
    return _CACHE["v"]
