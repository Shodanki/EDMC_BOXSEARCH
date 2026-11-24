# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""A4 (5.1.0): the FIS's own online requests per UTC day in fis_calls.json -
counted across FIS restarts, and the plugin counts them into its cap."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import callcount as cc  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, cc.FILE_NAME)
        t = [86400.0 * 20000 + 3600]                       # a day, 01:00 UTC
        clock = lambda: t[0]                               # noqa: E731
        assert cc.today(path, clock) == {} and cc.today(None) == {}
        assert cc.add(path, {"spansh": 2}, clock) == {"spansh": 2}
        assert cc.add(path, {"spansh": 1, "edsm": 0}, clock) == {"spansh": 3}
        assert cc.today(path, clock) == {"spansh": 3}, "kept across a restart (read back from the file)"
        t[0] += 86400                                      # next UTC day: from 0
        assert cc.today(path, clock) == {}
        assert cc.add(path, {"spansh": 1}, clock) == {"spansh": 1}
        assert [f for f in os.listdir(d) if f.endswith(".tmp")] == [], "no temporary file left"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        assert cc.today(path, clock) == {}, "a broken file counts as none"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"day": "x"}, fh)
        assert cc.today(path, clock) == {}
    assert cc.plugin_path("P").replace("\\", "/") == "P/FIS/fis_calls.json"
    with open(os.path.join(HERE, "load.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "ST.db.external_calls_since(day0, k) + fis_calls.get(k, 0)" in src, "plugin seeds with the FIS's count"
    print("call count: ok")


if __name__ == "__main__":
    main()
