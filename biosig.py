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

from typing import Any, Dict, Iterable, Optional, Set

# genera whose one signal can stand for several species on a body
MULTI_SPECIES_GENERA = ("Brain Trees",)
# how their species names end ("Lividum Brain Tree") -> the genus
_SPECIES_SUFFIX = {"Brain Tree": "Brain Trees"}

__all__ = ["MULTI_SPECIES_GENERA", "species_name", "genus_of", "open_bio"]


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


def _open_in_genus(g: str, done: Dict[str, Set[str]], seen_by: Dict[str, Set[str]]) -> int:
    if g not in MULTI_SPECIES_GENERA:
        return 0 if done.get(g) else 1
    if not seen_by.get(g) and not done.get(g):
        return 1                                # signalled, nothing known yet
    return len(seen_by.get(g, set()) - done.get(g, set()))
