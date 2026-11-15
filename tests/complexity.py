# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Complexity (4.11, all of it since 4.12): EDMC measures plugins with
``flake8 --max-complexity 15 --select C901``. Every function of the plugin
and the FIS stays at 15 or below; since 4.12 the project's .flake8 sets the
same limit, and this test also counts the FIS's own folders. 4.11 had 35
older functions above it (listed in LEGACY, not allowed to grow); 4.12
split them all, checked against the old code. LEGACY is empty.

    python tests/complexity.py      (from the plugin folder; needs flake8's mccabe)
"""
import ast
import os
import sys

import mccabe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 15
SKIP_DIRS = {"tests", "edts_pgnames", "regionmap", "vendor", "__pycache__", ".git", ".github"}

# 4.12: empty - every function of the plugin and the FIS keeps the limit.
# Kept as the place for an exception, should one ever be unavoidable.
LEGACY: dict = {}


def measure():
    """(file, function) -> complexity for everything above LIMIT."""
    found = {}
    for top, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(top, fn)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            with open(path, encoding="utf-8") as fh:
                tree = compile(fh.read(), path, "exec", ast.PyCF_ONLY_AST)
            visitor = mccabe.PathGraphingAstVisitor()
            visitor.preorder(tree, visitor)
            for graph in visitor.graphs.values():
                c = graph.complexity()
                if c > LIMIT:
                    found[(rel, graph.entity)] = c
    return found


def main() -> int:
    found = measure()
    bad = []
    for key, c in sorted(found.items()):
        allowed = LEGACY.get(key, LIMIT)
        if c > allowed:
            bad.append("%s %s: %d (allowed %d)" % (key[0], key[1], c, allowed))
    gone = sorted(k for k in LEGACY if k not in found)
    print("functions above %d: %d (listed legacy: %d)" % (LIMIT, len(found), len(LEGACY)))
    for line in bad:
        print("  [FAIL] " + line)
    if gone:
        print("  now at or below %d - remove from LEGACY: %s" % (LIMIT, ", ".join("%s %s" % k for k in gone)))
    print("complexity: %s" % ("all OK" if not bad else "%d FAILED" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
