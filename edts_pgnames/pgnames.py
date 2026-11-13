# -*- coding: utf-8 -*-
# Derived from EDTS (https://bitbucket.org/Esvandiary/edts), file
# edtslib/pgnames.py (and jenkins32 / interleave from edtslib/util.py) at
# commit 5d65cb65a53c5a814dab0421823243a5522c4c30.
# Copyright (c) 2016, Andy Martin. All rights reserved.
# BSD 3-Clause licence - full text in LICENSE.txt next to this file.
# The relative-position maths is by CMDR Jackie Silver, as EDTS notes.
# Modified for SHBOXSEARCH (2026, Shodanki): Python 3 only, no logging,
# sectors as absolute index tuples (0..127, as procgen.py counts them)
# instead of EDTS's PGSector objects, positions as plain (x, y, z), only
# the functions the plugin needs, plus ha_regions_near(). The name
# arithmetic (fragments, run lengths, offsets, class 1 / class 2 choice)
# is EDTS's, step for step.
# SPDX-License-Identifier: BSD-3-Clause
"""
Sector names of the Elite Dangerous galaxy, computed instead of learnt.

* sector_name(idx)       name of the procedural sector at an absolute index
* sector_index(name)     absolute index of a procedural sector name
* ha_region(name)        hand-authored sector by name (or None)
* ha_region_at(pos)      hand-authored sector a position falls in (or None)
* ha_regions_near(c, r)  hand-authored sectors touching a sphere
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import pgdata
from ._geom import BASE_COORDS, GALAXY_ORIGIN, SECTOR_SIZE, HARegion

GALAXY_SIZE = (128, 128, 128)
_EXPECTED_FRAGMENT_LIMIT = 4

# region list, smallest first (pgdata keeps them sorted by size) - the
# first region that contains a point names it
_HA_LIST: List[HARegion] = list(pgdata.ha_regions.values())


# ---------------------------------------------------------------------------
# util.py parts
# ---------------------------------------------------------------------------

def _jenkins32(key: int) -> int:
    key += (key << 12)
    key &= 0xFFFFFFFF
    key ^= (key >> 22)
    key += (key << 4)
    key &= 0xFFFFFFFF
    key ^= (key >> 9)
    key += (key << 10)
    key &= 0xFFFFFFFF
    key ^= (key >> 2)
    key += (key << 7)
    key &= 0xFFFFFFFF
    key ^= (key >> 12)
    return key


def _interleave(val1: int, val2: int, maxbits: int) -> int:
    output = 0
    for i in range(0, maxbits // 2 + 1):
        output |= ((val1 >> i) & 1) << (i * 2)
    for i in range(0, maxbits // 2 + 1):
        output |= ((val2 >> i) & 1) << (i * 2 + 1)
    return output & (2 ** maxbits - 1)


def _deinterleave(val: int, maxbits: int) -> Tuple[int, int]:
    out1 = 0
    out2 = 0
    for i in range(0, maxbits, 2):
        out1 |= ((val >> i) & 1) << (i // 2)
    for i in range(1, maxbits, 2):
        out2 |= ((val >> i) & 1) << (i // 2)
    return (out1, out2)


# ---------------------------------------------------------------------------
# run-length tables (EDTS _construct_offsets)
# ---------------------------------------------------------------------------

def _prefix_run_length(frag: str) -> int:
    return pgdata.cx_prefix_length_overrides.get(frag, pgdata.cx_prefix_length_default)


def _c1_infix_run_length(frag: str) -> int:
    if frag in pgdata.c1_infixes_s1:
        def_len = pgdata.c1_infix_s1_length_default
    else:
        def_len = pgdata.c1_infix_s2_length_default
    return pgdata.c1_infix_length_overrides.get(frag, def_len)


def _c1_infix_total_run_length(frag: str) -> int:
    if frag in pgdata.c1_infixes_s1:
        return pgdata.c1_infix_s1_total_run_length
    return pgdata.c1_infix_s2_total_run_length


_PREFIX_OFFSETS: Dict[str, Tuple[int, int]] = {}
_C1_INFIX_OFFSETS: Dict[str, Tuple[int, int]] = {}


def _construct_offsets() -> None:
    cnt = 0
    for p in pgdata.cx_prefixes:
        plen = _prefix_run_length(p)
        _PREFIX_OFFSETS[p] = (cnt, plen)
        cnt += plen
    for series in (pgdata.c1_infixes_s1, pgdata.c1_infixes_s2):
        cnt = 0
        for i in series:
            ilen = _c1_infix_run_length(i)
            _C1_INFIX_OFFSETS[i] = (cnt, ilen)
            cnt += ilen


_construct_offsets()


def _entry_from_offset(offset: int, keys, data) -> str:
    return [c for c in keys if data[c][0] <= offset < data[c][0] + data[c][1]][0]


# ---------------------------------------------------------------------------
# fragments
# ---------------------------------------------------------------------------

def sector_fragments(sector_name: str, allow_long: bool = False) -> Optional[List[str]]:
    """"Dryau Aowsy" -> ["Dry", "au", "Ao", "wsy"]; None if it is no
    procedural sector name."""
    current = sector_name.title().replace(" ", "")
    segments: List[str] = []
    while current:
        for frag in pgdata.cx_fragments:
            if current[0:len(frag)] == frag:
                segments.append(frag)
                current = current[len(frag):]
                break
        else:
            break
    if not current and (allow_long or len(segments) <= _EXPECTED_FRAGMENT_LIMIT):
        return segments
    return None


def format_sector_name(frags: Sequence[str]) -> str:
    if len(frags) == 4 and frags[2] in pgdata.cx_prefixes:
        return "{0}{1} {2}{3}".format(*frags)
    return "".join(frags)


def _sector_class(frags: Optional[Sequence[str]]) -> Optional[int]:
    if frags is not None and len(frags) == 4 and frags[0] in pgdata.cx_prefixes \
            and frags[2] in pgdata.cx_prefixes:
        return 2
    if frags is not None and len(frags) in (3, 4) and frags[0] in pgdata.cx_prefixes:
        return 1
    return None


def _suffixes(frags: Sequence[str], get_all: bool = False) -> List[str]:
    wordstart = frags[0]
    if frags[-1] in pgdata.cx_prefixes:
        # suffix straight onto a prefix (class 2)
        idx = pgdata.c2_prefix_suffix_override_map.get(frags[-1], 1)
        result = pgdata.c2_suffixes[idx]
        wordstart = frags[-1]
    else:
        # class 1
        if frags[-1] in pgdata.c1_infixes[2]:
            result = pgdata.c1_suffixes[1]
        else:
            result = pgdata.c1_suffixes[2]
    if get_all:
        return result
    return result[0:_prefix_run_length(wordstart)]


def _c1_infixes(frags: Sequence[str]) -> Optional[List[str]]:
    last = frags[-1]
    if last in pgdata.cx_prefixes:
        if last in pgdata.c1_prefix_infix_override_map:
            return pgdata.c1_infixes[pgdata.c1_prefix_infix_override_map[last]]
        return pgdata.c1_infixes[1]
    if last in pgdata.c1_infixes[1]:
        return pgdata.c1_infixes[2]
    if last in pgdata.c1_infixes[2]:
        return pgdata.c1_infixes[1]
    return None


def is_valid_sector_name(name: str) -> bool:
    frags = sector_fragments(name)
    if not frags or frags[0] not in pgdata.cx_prefixes:
        return False
    if len(frags) == 4 and frags[2] in pgdata.cx_prefixes:
        f1 = pgdata.c2_prefix_suffix_override_map.get(frags[0], 1)
        f3 = pgdata.c2_prefix_suffix_override_map.get(frags[2], 1)
        return frags[1] in pgdata.c2_suffixes[f1] and frags[3] in pgdata.c2_suffixes[f3]
    if len(frags) in (3, 4):
        fli = pgdata.c1_prefix_infix_override_map.get(frags[0], 1)
        if frags[1] not in pgdata.c1_infixes[fli]:
            return False
        if len(frags) == 4:
            fli = 2 if fli == 1 else 1
            if frags[2] not in pgdata.c1_infixes[fli]:
                return False
        flast = 2 if fli == 1 else 1
        return frags[-1] in pgdata.c1_suffixes[flast]
    return False


# ---------------------------------------------------------------------------
# offset <-> absolute sector index
# ---------------------------------------------------------------------------

def _offset_of_index(idx: Sequence[int]) -> int:
    return idx[2] * GALAXY_SIZE[1] * GALAXY_SIZE[0] + idx[1] * GALAXY_SIZE[0] + idx[0]


def _index_of_offset(offset: int) -> Optional[Tuple[int, int, int]]:
    x = offset % GALAXY_SIZE[0]
    y = (offset // GALAXY_SIZE[0]) % GALAXY_SIZE[1]
    z = offset // (GALAXY_SIZE[0] * GALAXY_SIZE[1])
    if z >= GALAXY_SIZE[2]:
        return None
    return (x, y, z)


def _c1_or_c2(offset: int) -> int:
    return (_jenkins32(offset) % 2) + 1


# ---------------------------------------------------------------------------
# class 1
# ---------------------------------------------------------------------------

def _c1_offset_from_name(frags: Sequence[str]) -> Optional[int]:
    try:
        sufs = _suffixes(frags[0:-1], True)
        suf_offset = sufs.index(frags[-1])
        f3_offset = suf_offset
        if len(frags) > 3:
            suf_offset += (sufs.index(frags[-1]) // _c1_infix_run_length(frags[2])) \
                * _c1_infix_total_run_length(frags[2])
            f3_offset, f3_mod = divmod(suf_offset, _c1_infix_run_length(frags[2]))
            f3_offset *= _c1_infix_total_run_length(frags[2])
            f3_offset += f3_mod
            f3_offset += _C1_INFIX_OFFSETS[frags[2]][0]
        f2_offset, f2_mod = divmod(f3_offset, _c1_infix_run_length(frags[1]))
        f2_offset *= _c1_infix_total_run_length(frags[1])
        f2_offset += f2_mod
        f2_offset += _C1_INFIX_OFFSETS[frags[1]][0]
        offset, offset_mod = divmod(f2_offset, _prefix_run_length(frags[0]))
        offset *= pgdata.cx_prefix_total_run_length
        offset += offset_mod
        offset += _PREFIX_OFFSETS[frags[0]][0]
        return offset
    except (ValueError, KeyError, IndexError):
        return None


def _c1_name(offset: int) -> List[str]:
    prefix_cnt, cur = divmod(offset, pgdata.cx_prefix_total_run_length)
    prefix = _entry_from_offset(cur, _PREFIX_OFFSETS, _PREFIX_OFFSETS)
    cur -= _PREFIX_OFFSETS[prefix][0]

    infix1s = _c1_infixes([prefix])
    infix1_total = _c1_infix_total_run_length(infix1s[0])
    infix1_cnt, cur = divmod(prefix_cnt * _prefix_run_length(prefix) + cur, infix1_total)
    infix1 = _entry_from_offset(cur, infix1s, _C1_INFIX_OFFSETS)
    cur -= _C1_INFIX_OFFSETS[infix1][0]

    infix1_run = _c1_infix_run_length(infix1)
    sufs = _suffixes([prefix, infix1], True)
    next_idx = (infix1_run * infix1_cnt) + cur
    frags = [prefix, infix1]
    if next_idx >= len(sufs):
        # past all three-phoneme names: an extra infix before the suffix
        infix2s = _c1_infixes(frags)
        infix2_total = _c1_infix_total_run_length(infix2s[0])
        infix2_cnt, cur = divmod(infix1_cnt * _c1_infix_run_length(infix1) + cur, infix2_total)
        infix2 = _entry_from_offset(cur, infix2s, _C1_INFIX_OFFSETS)
        cur -= _C1_INFIX_OFFSETS[infix2][0]
        infix2_run = _c1_infix_run_length(infix2)
        sufs = _suffixes([prefix, infix1, infix2], True)
        next_idx = (infix2_run * infix2_cnt) + cur
        frags.append(infix2)
    frags.append(sufs[next_idx])
    return frags


# ---------------------------------------------------------------------------
# class 2
# ---------------------------------------------------------------------------

def _c2_name(offset: int) -> List[str]:
    idx0, idx1 = _deinterleave(offset, 32)
    p0 = _entry_from_offset(idx0, _PREFIX_OFFSETS, _PREFIX_OFFSETS)
    p1 = _entry_from_offset(idx1, _PREFIX_OFFSETS, _PREFIX_OFFSETS)
    s0 = _suffixes([p0])[idx0 - _PREFIX_OFFSETS[p0][0]]
    s1 = _suffixes([p1])[idx1 - _PREFIX_OFFSETS[p1][0]]
    return [p0, s0, p1, s1]


def _c2_offset_from_name(frags: Sequence[str]) -> Optional[int]:
    try:
        idx0 = _PREFIX_OFFSETS[frags[0]][0] + _suffixes([frags[0]]).index(frags[1])
        idx1 = _PREFIX_OFFSETS[frags[2]][0] + _suffixes([frags[2]]).index(frags[3])
    except (ValueError, KeyError, IndexError):
        return None
    return _interleave(idx0, idx1, 32)


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

_NAME_CACHE: Dict[Tuple[int, int, int], str] = {}


def sector_name(idx: Sequence[int]) -> Optional[str]:
    """Name of the procedural sector at absolute index (0..127 per axis).
    Hand-authored sectors laid over it are not considered here."""
    key = (int(idx[0]), int(idx[1]), int(idx[2]))
    if not all(0 <= v < 128 for v in key):
        return None
    hit = _NAME_CACHE.get(key)
    if hit is None:
        offset = _offset_of_index(key)
        frags = _c1_name(offset) if _c1_or_c2(offset) == 1 else _c2_name(offset)
        hit = _NAME_CACHE[key] = format_sector_name(frags)
    return hit


def sector_index(name: str) -> Optional[Tuple[int, int, int]]:
    """Absolute index of a procedural sector name, or None (hand-authored
    names and anything that is no sector name)."""
    if not name or name.lower() in pgdata.ha_regions:
        return None
    frags = sector_fragments(name)
    if frags is None:
        return None
    sc = _sector_class(frags)
    if sc == 2:
        offset = _c2_offset_from_name(frags)
    elif sc == 1:
        offset = _c1_offset_from_name(frags)
    else:
        return None
    if offset is None:
        return None
    idx = _index_of_offset(offset)
    # only a name that computes back to itself counts
    if idx is None or (sector_name(idx) or "").lower() != format_sector_name(frags).lower():
        return None
    return idx


def ha_region(name: str) -> Optional[HARegion]:
    return pgdata.ha_regions.get((name or "").lower())


def ha_region_at(pos: Sequence[float]) -> Optional[HARegion]:
    """The hand-authored sector a position belongs to - the smallest one
    whose spheres contain it, as EDTS decides - or None."""
    for r in _HA_LIST:
        if r.contains(pos):
            return r
    return None


def ha_regions_near(center: Sequence[float], radius: float) -> List[HARegion]:
    """Hand-authored sectors with a sphere that meets this sphere, smallest
    first."""
    out = []
    for r in _HA_LIST:
        for s in r.spheres:
            if math.dist(s.centre, center) <= s.radius + radius:
                out.append(r)
                break
    return out


__all__ = ["sector_name", "sector_index", "ha_region", "ha_region_at",
           "ha_regions_near", "sector_fragments", "format_sector_name",
           "is_valid_sector_name", "HARegion", "GALAXY_ORIGIN", "SECTOR_SIZE",
           "BASE_COORDS"]
