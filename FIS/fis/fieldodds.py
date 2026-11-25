# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
MP4 (5.1.0, user 24.11.): the chance that a mining field turns out good,
before mining there - learnt from the fields MP3 rated, so every newly mined
field teaches it. The model lives in the plugin's miningfields.py (SP2: the
overlay shows the same chance); here the FIS's database and a cache - the
live view asks every few seconds.
"""
import threading
from typing import Any, Dict, List, Optional, Tuple

from .model import _optional

MIN_FIELDS = 3
THIN_FIELDS = 10

_lock = threading.Lock()
_cache: Dict[str, Tuple[Any, Any]] = {}


def mf() -> Any:
    """The plugin's miningfields module (5.1.0+), or None."""
    return _optional("miningfields")


def ring_features(db: Any) -> Dict[str, Dict[str, Any]]:
    """ring name -> class, reserve, hotspots from the plugin database."""
    m = mf()
    if db is None or m is None:
        return {}
    return m.ring_features(db.query)


def features(ring: Optional[str], mat: str, rf: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """What is known of a field before mining it."""
    return mf().features(ring, mat, rf)


def verdict(p: Optional[float]) -> Optional[str]:
    """'good' / 'open' / 'poor' for a chance."""
    return mf().verdict(p)


def reality(smp: List[Tuple[Any, int]]) -> Optional[Dict[str, Any]]:
    """Leave one out: each rated field predicted from all the others."""
    return mf().reality(smp)


def model(events: List[Dict[str, Any]], db: Any) -> Tuple[Any, Dict[str, Dict[str, Any]], List[Tuple[Any, int]]]:
    """The model, the ring features and the samples - rebuilt only when the
    journals moved."""
    sig = (len(events), events[-1].get("timestamp") if events else None, id(db))
    with _lock:
        hit = _cache.get("model")
        if hit and hit[0] == sig:
            return hit[1]
    from . import fieldrating
    m = mf()
    rf = ring_features(db)
    rows = fieldrating.rate_fields(events)
    smp = m.samples(rows, rf)
    val = (m.Odds.learn(smp), rf, smp)
    with _lock:
        _cache["model"] = (sig, val)
        _cache["rated"] = (sig, rows)
    return val


def rated(events: List[Dict[str, Any]], db: Any) -> List[Dict[str, Any]]:
    """The rated fields the model learnt from (same cache)."""
    sig = (len(events), events[-1].get("timestamp") if events else None, id(db))
    with _lock:
        hit = _cache.get("rated")
        if hit and hit[0] == sig:
            return hit[1]
    model(events, db)
    with _lock:
        return _cache["rated"][1]


def odds_for(m: Any, rf: Dict[str, Dict[str, Any]], ring: Optional[str],
             mat: Optional[str]) -> Optional[Dict[str, Any]]:
    """The chance for one field, with what it rests on - for the FIS."""
    return mf().odds_for(m, rf, ring, mat)
