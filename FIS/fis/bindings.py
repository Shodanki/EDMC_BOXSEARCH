# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FG1 (4.12): the commander's key bindings for the controls an explorer uses -
read from the game's own files, only while the controls view is switched on
in the FIS settings (off by default), and never written.

The game keeps them in Options\\Bindings: StartPreset.4.start names the
preset in use for each part (general, ship, SRV, on foot), and each custom
preset is a <name>.<major>.<minor>.binds XML file. A preset that comes with
the game has no file there - its bindings are in the game folder, which the
FIS does not read; the view says so.

What is in a fire group is in no game file the FIS may read (it lives in the
game's account data); the active fire group comes from Status.json.
"""

from __future__ import annotations

import glob
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

BINDINGS_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Frontier Developments",
                            "Elite Dangerous", "Options", "Bindings")
MAX_BYTES = 2_000_000                 # a .binds file is about 70 KB
PARTS = ("general", "ship", "srv", "foot")   # the lines of StartPreset.4.start

# (part, action, label) - what an explorer reaches for, in that order
ACTIONS: List[Tuple[str, str, str]] = [
    ("ship", "HyperSuperCombination", "Jump / supercruise"),
    ("ship", "Supercruise", "Supercruise"),
    ("ship", "Hyperspace", "Hyperspace jump"),
    ("ship", "TargetNextRouteSystem", "Next system in route"),
    ("ship", "ExplorationFSSEnter", "Full spectrum scanner (FSS)"),
    ("ship", "PlayerHUDModeToggle", "HUD: analysis / combat"),
    ("ship", "CycleFireGroupNext", "Next fire group"),
    ("ship", "CycleFireGroupPrevious", "Previous fire group"),
    ("ship", "PrimaryFire", "Primary fire"),
    ("ship", "SecondaryFire", "Secondary fire"),
    ("ship", "DeployHardpointToggle", "Hardpoints"),
    ("ship", "LandingGearToggle", "Landing gear"),
    ("ship", "ToggleCargoScoop", "Cargo scoop"),
    ("ship", "ShipSpotLightToggle", "Ship lights"),
    ("ship", "NightVisionToggle", "Night vision"),
    ("ship", "ToggleFlightAssist", "Flight assist"),
    ("ship", "UseBoostJuice", "Boost"),
    ("ship", "GalaxyMapOpen", "Galaxy map"),
    ("ship", "SystemMapOpen", "System map"),
    ("srv", "RecallDismissShip", "Recall / dismiss ship"),
    ("srv", "HeadlightsBuggyButton", "SRV lights"),
    ("srv", "ToggleBuggyTurretButton", "SRV turret"),
    ("foot", "HumanoidSwitchToSuitTool", "Suit tool (genetic sampler)"),
    ("foot", "HumanoidSwitchToCompAnalyser", "Composition scanner"),
    ("foot", "HumanoidToggleFlashlightButton", "Flashlight"),
    ("foot", "HumanoidToggleNightVisionButton", "Night vision"),
    ("foot", "HumanoidPrimaryInteractButton", "Interact"),
]


def active_presets(folder: str = BINDINGS_DIR) -> List[str]:
    """The preset per part (general, ship, SRV, on foot) from StartPreset;
    one name stands for all four in older files."""
    for name in ("StartPreset.4.start", "StartPreset.start"):
        p = os.path.join(folder, name)
        try:
            with open(p, encoding="utf-8-sig") as fh:
                lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
        except OSError:
            continue
        if lines:
            return (lines + [lines[-1]] * len(PARTS))[:len(PARTS)]
    return []


def preset_file(preset: str, folder: str = BINDINGS_DIR) -> Optional[str]:
    """The newest <preset>.<major>.<minor>.binds (or <preset>.binds), None
    for a preset that comes with the game (no file in Options\\Bindings)."""
    best: Optional[Tuple[Tuple[int, ...], str]] = None
    for p in glob.glob(os.path.join(glob.escape(folder), glob.escape(preset) + ".*binds")):
        m = re.fullmatch(re.escape(preset) + r"(?:\.(\d+)\.(\d+))?\.binds", os.path.basename(p))
        if m:
            ver = tuple(int(g) for g in m.groups() if g is not None)
            if best is None or ver > best[0]:
                best = (ver, p)
    return best[1] if best else None


def key_text(node: Optional[ET.Element]) -> Optional[str]:
    """'U', 'LeftAlt + V', 'Joy 11 (ThrustMasterTFlightHOTASX)' - or None."""
    if node is None:
        return None
    dev, key = node.get("Device") or "", node.get("Key") or ""
    if not key or dev == "{NoDevice}":
        return None

    def one(d: str, k: str) -> str:
        k = k[4:] if k.startswith("Key_") else k
        k = k.replace("_", " ")
        return k if d in ("Keyboard", "Mouse") else "%s (%s)" % (k, d)
    mods = [one(m.get("Device") or "", m.get("Key") or "") for m in node.findall("Modifier") if m.get("Key")]
    return " + ".join(mods + [one(dev, key)])


def _parse(path: str) -> Optional[ET.Element]:
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None


def read(folder: str = BINDINGS_DIR) -> Dict[str, Any]:
    """The bindings of ACTIONS, per part: {"presets", "files", "builtin",
    "parts": {part: [{"action", "label", "keys": [...]}]}}, or {"error"}."""
    presets = active_presets(folder)
    if not presets:
        return {"error": "no StartPreset file in the Bindings folder"}
    roots: Dict[str, Optional[ET.Element]] = {}
    files: Dict[str, Optional[str]] = {}
    for preset in dict.fromkeys(presets):
        files[preset] = preset_file(preset, folder)
        roots[preset] = _parse(files[preset]) if files[preset] else None
    by_part = dict(zip(PARTS, presets))
    parts: Dict[str, List[Dict[str, Any]]] = {}
    for part, action, label in ACTIONS:
        root = roots.get(by_part.get(part, presets[0]))
        node = root.find(action) if root is not None else None
        if node is None:
            continue
        keys = [k for k in (key_text(node.find("Primary")), key_text(node.find("Secondary"))) if k]
        parts.setdefault(part, []).append({"action": action, "label": label, "keys": keys})
    return {"presets": by_part, "files": sorted({os.path.basename(f) for f in files.values() if f}),
            "builtin": sorted(p for p, f in files.items() if not f), "parts": parts}
