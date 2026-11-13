# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SHBOX FIS - flight information system, shipped with the SHBOXSEARCH plugin.

Reads only: the plugin database (read-only), the journal, Status.json,
NavRoute.json and the other state files the game writes. No input to the game,
no AI at runtime, Python standard library only.
"""

__version__ = "4.10.0"      # released together with the plugin
