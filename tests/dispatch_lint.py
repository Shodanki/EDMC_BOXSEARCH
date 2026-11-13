# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Dispatch lint (5.0): no value may appear in two branches of one if/elif
chain on the same subject (`ev`, `kind`, `e["event"]`, `e.get("event")` ...).
The first matching branch wins, so the later one is dead code - up to 4.9
that silently switched off the live DSS timing (ApproachBody) and the own
carrier refresh after a CarrierJump. Checks every plugin module and the FIS.

Reads the source only (ast), nothing is imported or run.

    python tests/dispatch_lint.py      (from the plugin folder)
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = sorted(os.path.basename(f) for f in glob.glob(os.path.join(ROOT, "*.py")))


def _subject(node):
    """A stable key for what a branch compares: a name (ev), a subscript
    (e["event"]) or a call (e.get("event")). None for anything else."""
    if isinstance(node, (ast.Name, ast.Subscript, ast.Call, ast.Attribute)):
        return ast.dump(node)
    return None


def _names(test):
    """(subject, value) pairs a branch test compares (ev == "X", ev in (...)).
    Only a literal tuple / list / set after `in` counts: `x in "ABC"` is a
    substring test, not a dispatch."""
    out = set()
    for n in ast.walk(test):
        if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.ops[0], (ast.Eq, ast.In))):
            continue
        subj = _subject(n.left)
        if subj is None:
            continue
        c = n.comparators[0]
        if isinstance(n.ops[0], ast.Eq):
            vals = [c]
        elif isinstance(c, (ast.Tuple, ast.List, ast.Set)):
            vals = c.elts
        else:
            continue
        for k in vals:
            if isinstance(k, ast.Constant) and isinstance(k.value, (str, int)) \
                    and not isinstance(k.value, bool):
                out.add((subj, k.value))
    return out


def _guarded(test):
    """A branch like `ev == "X" and cond` does not catch every X: later
    branches may still see X. Only a plain `ev == / ev in` (or an `or` of
    them) claims the name for good."""
    if isinstance(test, ast.Compare):
        return False
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(_guarded(v) for v in test.values)
    return True


def lint(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = []
    seen_if = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or id(node) in seen_if:
            continue
        claimed = {}
        cur = node
        while isinstance(cur, ast.If):
            seen_if.add(id(cur))
            names = _names(cur.test)
            plain = set()
            if isinstance(cur.test, ast.BoolOp) and isinstance(cur.test.op, ast.Or):
                for v in cur.test.values:
                    if not _guarded(v):
                        plain |= _names(v)
            elif not _guarded(cur.test):
                plain = names
            for n in sorted(names, key=repr):
                if n in claimed:
                    found.append("%s:%d %r already caught in line %d"
                                 % (os.path.basename(path), cur.lineno, n[1], claimed[n]))
            for n in plain:
                claimed.setdefault(n, cur.lineno)
            if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                cur = cur.orelse[0]
            else:
                break
    return found


def _selftest_lint():
    import tempfile
    bad = ("def f(ev):\n    if ev in ('A', 'B'):\n        pass\n    elif ev == 'A':\n        pass\n"
           "    elif ev == 'C' and x:\n        pass\n    elif ev == 'C':\n        pass\n"
           "def g(e, kind):\n    if e.get('event') == 'X':\n        pass\n"
           "    elif e['event'] == 'X':\n        pass\n    elif e.get('event') == 'X':\n        pass\n"
           "    elif kind == 'X':\n        pass\n    elif kind in 'XY':\n        pass\n")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write(bad)
        got = lint(p)
    return len(got) == 2 and "'A'" in got[0] and "'X'" in got[1] and ":15 " in got[1] and "line 11" in got[1]


fails = 0
if not _selftest_lint():
    print("  [FAIL] the lint finds a dead branch and allows a guarded one")
    fails += 1
else:
    print("  [OK] the lint finds a dead branch and allows a guarded one")
for fn in FILES + sorted(glob.glob(os.path.join(ROOT, "FIS", "fis", "*.py"))):
    path = fn if os.path.isabs(fn) else os.path.join(ROOT, fn)
    for msg in lint(path):
        print("  [FAIL] dead branch: " + msg)
        fails += 1
print("dispatch lint: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
