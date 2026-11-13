# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""python -m fis: start SHBOX FIS (start_fis.bat does this)."""
import sys

from . import python_problem

if python_problem():
    sys.exit(python_problem())

from .server import main  # noqa: E402  (needs 3.11: tomllib)

sys.exit(main())
