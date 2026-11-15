# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Docstrings (4.12, S6 of the EDMC listing check): every module of the plugin
and the FIS, every EDMC hook and every public function and class (no
leading underscore, methods included) says what it does - for a reviewer
reading the code, and so that nothing new comes in without one.

Third-party folders (edts_pgnames, regionmap, FIS/fis/vendor) are left as
their authors wrote them.

    python tests/docstrings.py      (from the plugin folder)
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "FIS", "fis", "*.py")))


def missing(path):
    """Names in one file that should have a docstring and have none."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = [] if ast.get_docstring(tree) else ["(module)"]

    def walk(body, prefix=""):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not n.name.startswith("_") and not ast.get_docstring(n):
                    out.append("%s%s:%d" % (prefix, n.name, n.lineno))
                if isinstance(n, ast.ClassDef):
                    walk(n.body, prefix + n.name + ".")
    walk(tree.body)
    return out


fails = 0
total = 0
for f in FILES:
    gaps = missing(f)
    total += 1
    if gaps:
        fails += len(gaps)
        print("  [FAIL] %s: %s" % (os.path.relpath(f, ROOT), ", ".join(gaps)))
print("  [%s] %d files: every module and public function has a docstring"
      % ("OK" if not fails else "FAIL", total))
print("docstrings: %s" % ("all OK" if not fails else "%d missing" % fails))
sys.exit(1 if fails else 0)
