# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SHBOXSEARCH as a Python package.

EDMC imports the plugin as "<folder>.load"; this file makes the folder a
regular package, so the plugin's modules import each other relatively
(``from . import netgate``) and none of their names collides with another
plugin's module. It runs nothing - EDMC's entry point is load.py.
"""
