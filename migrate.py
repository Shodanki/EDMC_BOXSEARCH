#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate.py - one-off import of legacy data into shboxsearch.sqlite
==================================================================
Reads neareststars.json, survey_state.json and the journals. Purely
additive; the source files are never modified.

Optional. The plugin performs the same import automatically on first start,
so a system-wide Python installation is not required.

    python migrate.py [PLUGIN_DIR] [JOURNAL_DIR]
"""
import json
import os
import sys

from sysdb import SystemDB
from boxelplan import Planner


def journal_dir_default():
    p = os.path.expandvars(
        r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous")
    return p if os.path.isdir(p) else None


def main() -> int:
    plugin_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    jdir = sys.argv[2] if len(sys.argv) > 2 else journal_dir_default()
    db_path = os.path.join(plugin_dir, "shboxsearch.sqlite")
    print("plugin folder   :", plugin_dir)
    print("database        :", db_path)
    db = SystemDB(db_path)

    ns = os.path.join(plugin_dir, "neareststars.json")
    if os.path.exists(ns):
        print("neareststars.json ->", "%d imported, %d skipped" % db.import_neareststars(ns))

    stf = os.path.join(plugin_dir, "survey_state.json")
    if os.path.exists(stf):
        print("survey_state.json ->", "%d systems, %d visited" % db.import_survey_state(stf))

    if jdir and os.path.isdir(jdir):
        print("journals        :", jdir)
        print("                ->", json.dumps(db.import_journals(jdir), ensure_ascii=False))
    else:
        print("journals        : folder not found, skipped")

    print("sectors learned :", db.sectors.to_dict())
    if db.sectors.conflicts:
        print("!! sector conflicts:", db.sectors.conflicts)
    print("statistics      :", json.dumps(db.stats(), ensure_ascii=False, indent=2))

    if os.path.exists(stf):
        st = json.load(open(stf, encoding="utf-8"))
        if st.get("start_coords"):
            plan = Planner(db).build(st["start_coords"], st.get("radius_ly", 50))
            print()
            print(Planner.summary(plan))
            print("\nnext flight targets:")
            for t in plan["flight"][:8]:
                print("  %-8s %-30s %6.1f ly  %s" % (t.kind, t.name, t.dist, t.detail))
            print("\nnext probes:")
            for t in plan["probe"][:8]:
                print("  %-8s %-30s %6.1f ly  +-%.0f ly" % (t.kind, t.name, t.dist, t.uncertainty))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
