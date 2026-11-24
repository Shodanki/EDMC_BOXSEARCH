# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Biological signals of a body: how much is still open.

The game reports one biological signal per genus. For the Odyssey genera a
body holds one species of each genus, so "signals minus species analysed"
counts what is open. The older organics differ: Brain Trees report one
signal, yet one body can carry several species - up to three in the
developer's journals (Gypseeum, Roseum and Lividum on HIP 31189 A 1 d) -
each sampled and paid on its own (Vista Genomics, 1 593 700 Cr each).
Which of them grow there shows only once they are scanned: the codex entry
names the species and the body.

Pure Python, no EDMC: used by the plugin (sysdb) and the FIS.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

# genera whose one signal can stand for several species on a body
MULTI_SPECIES_GENERA = ("Brain Trees",)
# how their species names end ("Lividum Brain Tree") -> the genus
_SPECIES_SUFFIX = {"Brain Tree": "Brain Trees"}
# 5.1.0: an overlay line of a finished species starts with this; the own
# overlay window draws it struck through instead, EDMCModernOverlay as it is
DONE_MARK = "✓ "
_ORDER = {"done": 0, "begun": 1, "todo": 2}

__all__ = ["MULTI_SPECIES_GENERA", "DONE_MARK", "species_name", "genus_of", "open_bio",
           "species_per_signal", "species_rows"]


def species_name(label: Optional[str]) -> str:
    """The species of a codex or sample name: 'Bacterium Acies - White'
    -> 'Bacterium Acies' (the colour variant goes)."""
    return (label or "").split(" - ")[0].strip()


def genus_of(species: Optional[str]) -> Optional[str]:
    """The genus of a species name: 'Lividum Brain Tree' -> 'Brain Trees',
    'Bacterium Acies' -> 'Bacterium' (Odyssey names start with it)."""
    sp = species_name(species)
    if not sp:
        return None
    for suffix, genus in _SPECIES_SUFFIX.items():
        if sp.endswith(suffix):
            return genus
    return sp.split(" ")[0]


def open_bio(signals: int, genera: Iterable[str], analysed: Iterable[Dict[str, Any]],
             seen: Iterable[str] = ()) -> Dict[str, Any]:
    """
    What is still open on one body.

    signals:  the body's biological signal count (FSS or DSS)
    genera:   the genera the DSS named (empty before the body is mapped)
    analysed: the commander's analysed species, {"species", "genus"}
    seen:     species names from codex entries on this body

    Returns {"open": signals still to sample (a multi-species genus counts
    each species seen and not analysed, at least one while none is known),
    "open_species": seen, not analysed, "multi": genera here that may hold
    more species than they report}.
    """
    genera = [g for g in genera if g]
    done: Dict[str, Set[str]] = {}
    for a in analysed:
        sp = species_name(a.get("species"))
        g = a.get("genus") or genus_of(sp)
        if sp and g:
            done.setdefault(g, set()).add(sp)
    seen_by: Dict[str, Set[str]] = {}
    for label in seen:
        sp = species_name(label)
        g = genus_of(sp)
        if g in MULTI_SPECIES_GENERA:
            seen_by.setdefault(g, set()).add(sp)
    open_species = sorted(sp for g, s in seen_by.items() for sp in s - done.get(g, set()))
    multi = sorted({g for g in [*genera, *seen_by, *done] if g in MULTI_SPECIES_GENERA})
    if genera:
        n = sum(_open_in_genus(g, done, seen_by) for g in set(genera) | set(seen_by))
    else:
        # before the DSS: the signal count; a multi-species genus known only
        # from the codex counts with its species instead of one signal
        seen_only = [g for g in seen_by if g not in done]
        n = max(0, int(signals or 0) - len(done) - len(seen_only)) + len(open_species)
    return {"open": n, "open_species": open_species, "multi": multi}


def species_rows(analysed: Iterable[Dict[str, Any]], progress: Iterable[Dict[str, Any]] = (),
                 genera: Iterable[str] = (), seen: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """
    5.1.0 (bio display, variant 1): every collectable bio of one body, one
    row each - the state logic the FIS's PLANET and the overlay share.

    analysed: species analysed here, {"species", "genus"}
    progress: species begun and not analysed, {"species", "genus", "samples"}
    genera:   the genera the DSS named
    seen:     species names from codex entries on this body

    Rows {"species", "genus", "state", "samples"} in the order finished
    ("done", 3/3), begun ("begun", 1-2/3), not started ("todo", 0/3). A
    "todo" row is a species the codex saw (several species of one signal,
    Brain Trees) or a genus none of whose species is done or begun - then
    "species" is None.
    """
    rows: List[Dict[str, Any]] = []
    have: Set[str] = set()
    covered: Set[str] = set()
    for state, src in (("done", analysed), ("begun", progress)):
        for a in src:
            sp = species_name(a.get("species"))
            if not sp or sp in have:
                continue
            g = a.get("genus") or genus_of(sp)
            have.add(sp)
            covered.add(g or "")
            rows.append({"species": sp, "genus": g, "state": state,
                         "samples": 3 if state == "done" else int(a.get("samples") or 0)})
    for label in seen:
        sp = species_name(label)
        g = genus_of(sp)
        if sp and sp not in have and g in MULTI_SPECIES_GENERA:
            have.add(sp)
            covered.add(g or "")
            rows.append({"species": sp, "genus": g, "state": "todo", "samples": 0})
    for g in genera:
        if g and g not in covered:
            covered.add(g)
            rows.append({"species": None, "genus": g, "state": "todo", "samples": 0})
    rows.sort(key=lambda r: _ORDER[r["state"]])
    return rows


def species_per_signal(finds: Iterable[Iterable[str]]) -> Dict[str, Any]:
    """
    BT2 (5.0): how many species of a multi-species genus one signal stood
    for, from the bodies where species of it were found (codex entries and
    samples) - one entry per body, the species names found there.

    Returns {"n": bodies, "mean", "lo", "hi", "dist": {species: bodies}}
    (mean None without a body). A lower bound: species growing out of
    sight of the commander are not in it. Measured on the developer's
    journals, 17.11.2026: Brain Trees 1 species on 2 bodies, 2 on 3, 3 on 2
    - mean 2.0, range 1-3, n = 7.
    """
    counts = [len({species_name(s) for s in f if species_name(s)}) for f in finds]
    counts = [c for c in counts if c > 0]
    dist: Dict[int, int] = {}
    for c in counts:
        dist[c] = dist.get(c, 0) + 1
    if not counts:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "dist": {}}
    return {"n": len(counts), "mean": round(sum(counts) / len(counts), 2), "lo": min(counts),
            "hi": max(counts), "dist": dict(sorted(dist.items()))}


def _open_in_genus(g: str, done: Dict[str, Set[str]], seen_by: Dict[str, Set[str]]) -> int:
    if g not in MULTI_SPECIES_GENERA:
        return 0 if done.get(g) else 1
    if not seen_by.get(g) and not done.get(g):
        return 1                                # signalled, nothing known yet
    return len(seen_by.get(g, set()) - done.get(g, set()))
