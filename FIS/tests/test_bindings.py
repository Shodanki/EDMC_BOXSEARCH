# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""FG1 (4.12): key bindings from the game's Options\\Bindings - read only."""

import os
import tempfile
import unittest

from fis import bindings

BINDS = """<?xml version="1.0" encoding="UTF-8" ?>
<Root PresetName="{name}" MajorVersion="4" MinorVersion="{minor}">
  <KeyboardLayout>de-DE</KeyboardLayout>
  <DeployHardpointToggle>
    <Primary Device="Keyboard" Key="Key_U" />
    <Secondary Device="ThrustMasterTFlightHOTASX" Key="Joy_11" />
  </DeployHardpointToggle>
  <NightVisionToggle>
    <Primary Device="Keyboard" Key="Key_LeftAlt"><Modifier Device="Keyboard" Key="Key_V" /></Primary>
    <Secondary Device="{{NoDevice}}" Key="" />
  </NightVisionToggle>
  <GalaxyMapOpen>
    <Primary Device="{{NoDevice}}" Key="" />
    <Secondary Device="{{NoDevice}}" Key="" />
  </GalaxyMapOpen>
  <ExplorationFSSEnter>
    <Primary Device="Keyboard" Key="Key_{fss}" />
    <Secondary Device="{{NoDevice}}" Key="" />
  </ExplorationFSSEnter>
  <HumanoidSwitchToSuitTool>
    <Primary Device="Keyboard" Key="Key_5" />
    <Secondary Device="{{NoDevice}}" Key="" />
  </HumanoidSwitchToSuitTool>
</Root>
"""


def folder(start, files):
    d = tempfile.mkdtemp(prefix="fis-binds-")
    if start is not None:
        with open(os.path.join(d, "StartPreset.4.start"), "w", encoding="utf-8") as fh:
            fh.write(start)
    for name, text in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    return d


class TestBindings(unittest.TestCase):
    def test_newest_custom_file_and_key_texts(self):
        d = folder("Custom\nCustom\nCustom\nCustom\n", {
            "Custom.4.1.binds": BINDS.format(name="Custom", minor=1, fss="F"),
            "Custom.4.2.binds": BINDS.format(name="Custom", minor=2, fss="ä"),
            "Custom.4.2.binds.1583799622.backup": "not xml at all",
        })
        r = bindings.read(d)
        self.assertEqual(r["files"], ["Custom.4.2.binds"])          # the newest, no backup
        ship = {a["action"]: a["keys"] for a in r["parts"]["ship"]}
        self.assertEqual(ship["DeployHardpointToggle"], ["U", "Joy 11 (ThrustMasterTFlightHOTASX)"])
        self.assertEqual(ship["NightVisionToggle"], ["V + LeftAlt"])   # held key first
        self.assertEqual(ship["GalaxyMapOpen"], [])                    # not bound
        self.assertEqual(ship["ExplorationFSSEnter"], ["ä"])          # the keyboard layout's key
        self.assertEqual([a["keys"] for a in r["parts"]["foot"]], [["5"]])
        self.assertNotIn("srv", r["parts"])                            # nothing of it in the file
        self.assertEqual(r["builtin"], [])

    def test_presets_per_part_and_builtin(self):
        d = folder("KeyboardMouseOnly\nCustom\nCustom\nOdysseyFoot\n", {
            "Custom.4.2.binds": BINDS.format(name="Custom", minor=2, fss="F")})
        r = bindings.read(d)
        self.assertEqual(r["presets"], {"general": "KeyboardMouseOnly", "ship": "Custom",
                                        "srv": "Custom", "foot": "OdysseyFoot"})
        self.assertEqual(r["builtin"], ["KeyboardMouseOnly", "OdysseyFoot"])  # in the game folder
        self.assertIn("ship", r["parts"])
        self.assertNotIn("foot", r["parts"])        # its preset is not readable here

    def test_one_line_preset_and_errors(self):
        d = folder("Custom\n", {"Custom.binds": BINDS.format(name="Custom", minor=0, fss="F")})
        r = bindings.read(d)
        self.assertEqual(set(r["presets"].values()), {"Custom"})
        self.assertEqual(r["files"], ["Custom.binds"])
        self.assertIn("error", bindings.read(folder(None, {})))
        broken = folder("Custom\n", {"Custom.4.2.binds": "<Root><unclosed></Root>"})
        self.assertEqual(bindings.read(broken)["parts"], {})              # unreadable: nothing shown


if __name__ == "__main__":
    unittest.main()
