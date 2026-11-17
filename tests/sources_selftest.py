# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of sources.py (moved from the module in 4.12, N7 - verbatim).

    python tests/sources_selftest.py      (from the plugin folder)
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.sources import (EDDiscoverySource)  # noqa: E402


def _selftest() -> int:
    """python sources.py - EDD name decoding, no files, no network."""
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    E = EDDiscoverySource
    cases = [
        (0x1000140000007a62, "HIP", "HIP 31330"),        # values from EDDSystem.sqlite
        (0x1000100000000956, "HR", "HR 2390"),
        ((1 << 60) | (7 << 42) | (5 << 38) | 1846031, "EXO", "EXO 1846-031"),
        ((1 << 60) | (6 << 42) | 4321, "HD", "HD 004321"),
    ]
    for nid, sec, want in cases:
        got = E.decode_nameid(nid, sec)
        check(got == want, "catalogue name %s (got %s)" % (want, got))
    std = (1 << 61) | (19 << 38) | (8 << 33) | (10 << 28) | (1 << 24) | 1
    check(E.decode_nameid(std, "Synuefe") == "Synuefe SH-J b1",
          "procgen name still decoded")
    check(E.decode_nameid(12345, "TYC") is None, "Names id is left to the Names table")
    check(E.with_sector("TYC", "3996-1327-1") == "TYC 3996-1327-1"
          and E.with_sector(E.NO_SECTOR, "15 Sagittarii") == "15 Sagittarii",
          "Names entries get their sector, except NoSectorName")
    # EDD freshness from its Register table (layout as in EDDSystem.sqlite)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "EDDSystem.sqlite")
        cx = sqlite3.connect(path)
        cx.execute("CREATE TABLE Register (ID TEXT PRIMARY KEY, ValueInt INTEGER,"
                   " ValueDouble DOUBLE, ValueString TEXT, ValueBlob BLOB)")
        cx.execute("INSERT INTO Register VALUES ('DBSource', NULL, NULL, 'SPANSH', NULL)")
        cx.execute("INSERT INTO Register VALUES ('EDSMLastSystems', NULL, NULL,"
                   " '11/09/2026 21:59:59', NULL)")
        cx.commit()
        cx.close()
        e = EDDiscoverySource(path)
        src, ts = e.freshness()
        check(src == "SPANSH" and ts == 1794261599.0, "EDD source and last update read")
        check(e.is_current("spansh", now=ts + 86400) and not e.is_current("edsm", now=ts + 86400),
              "EDD one day old holds Spansh's data, not EDSM's")
        check(not e.is_current("spansh", now=ts + 3 * 86400), "three days old: not current")
        # PM1: the permit list - taken when the source is Spansh, else empty
        cx = sqlite3.connect(path)
        cx.execute("CREATE TABLE PermitSystems (edsmid INTEGER PRIMARY KEY NOT NULL)")
        cx.executemany("INSERT INTO PermitSystems VALUES (?)", [(10477373803,), (3932277478106,)])
        cx.commit()
        cx.close()
        e = EDDiscoverySource(path)
        check(e.permit_ids() == {10477373803, 3932277478106}, "permit systems read from EDD (Spansh keys = id64)")
        cx = sqlite3.connect(path)
        cx.execute("UPDATE Register SET ValueString='EDSM' WHERE ID='DBSource'")
        cx.commit()
        cx.close()
        check(EDDiscoverySource(path).permit_ids() == set(), "EDSM-built file: no permit list (keys are no id64)")
        check(EDDiscoverySource(os.path.join(d, "none.sqlite")).permit_ids() == set(), "no file: empty")
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
