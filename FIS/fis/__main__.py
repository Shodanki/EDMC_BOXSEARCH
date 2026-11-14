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

from . import files  # noqa: E402

files.startup_check()                 # 4.12: every file of this version there?
try:
    from .server import main  # noqa: E402  (needs 3.11: tomllib)
except Exception as exc:              # a file of the FIS is missing or broken
    files.cannot_start(exc)
    sys.exit(1)

sys.exit(main())
