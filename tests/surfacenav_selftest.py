# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of surfacenav.py (moved from the module in 4.12, N7 - verbatim).

    python tests/surfacenav_selftest.py      (from the plugin folder)
"""
import calendar
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.surfacenav import (LINE_MAX, bearing_deg, body_state, compass_lines, course_text,  # noqa: E402
                                    direction_text, head_line)


def _selftest() -> None:
    assert round(bearing_deg(0, 0, 1, 0)) == 0
    assert round(bearing_deg(0, 0, 0, 1)) == 90
    assert direction_text(90, 90) == "^ ahead"
    assert direction_text(60, 90) == "< 30"
    assert direction_text(200, 90) == "110 >>"
    assert direction_text(275, 90) == "v behind"
    assert course_text(255.4, None) == "brg 255"
    assert course_text(255.0, 285.0) == "brg 255 < 30", course_text(255.0, 285.0)
    assert course_text(359.7, 0.0) == "brg 000 ^ ahead", course_text(359.7, 0.0)
    assert course_text(7.0, 0.0) == "brg 007 ^ ahead"
    marks = [
        {"ts": "1", "kind": "touchdown", "label": "b", "detail": "srv", "lat": 0.0, "lon": 0.0},
        {"ts": "2", "kind": "srv_parked", "label": "SRV", "detail": "Nomad", "lat": 0.0, "lon": 0.0},
        {"ts": "3", "kind": "bio_log", "label": "Roseum Brain Tree", "detail": "Brain Trees",
         "lat": 0.001, "lon": 0.0},
        {"ts": "3", "kind": "codex", "label": "Roseum Brain Tree", "detail": "Organic structures",
         "lat": 0.001, "lon": 0.0},
        {"ts": "4", "kind": "bio_sample", "label": "Roseum Brain Tree", "detail": "Brain Trees",
         "lat": 0.002, "lon": 0.0},
    ]
    st = body_state(marks)
    assert st["ship"] is None and st["parked"]["detail"] == "Nomad"
    assert st["species"][0]["samples"] == 2 and not st["species"][0]["analysed"]
    lines = compass_lines({"lat": 0.0, "lon": 0.001, "heading": 0}, marks, 400000.0,
                          sig_bio=2, genera=["Brain Trees", "Bacterium"])
    assert lines[1][0].startswith("NOMAD PARKED"), lines
    assert "to find: Bacterium" in lines[0][0], lines
    assert not any(ln[0].startswith("Roseum Brain Tree ") and "/3" not in ln[0]
                   for ln in lines), lines
    # every point names its absolute course next to the turn
    assert all(" brg " in ln[0] for ln in lines[1:]), lines
    assert all(len(ln[0]) <= 44 for ln in lines[1:]), lines   # the points; the head may run on
    assert len(compass_lines({"lat": 0.0, "lon": 0.0, "heading": 0.0}, [
        {"ts": "1", "kind": "codex", "label": "Very long find name of a site", "detail": None,
         "lat": 0.0, "lon": -1.0}], 400000.0)[1][0]) <= 44
    nomad = lines[1][0]
    assert nomad.endswith("brg 270 < 90"), nomad
    # lost in a crash (screenshot 12.11.: "bio 2 done" for two lost species)
    lm = [
        {"ts": "1", "kind": "bio_log", "label": "Stratum Tectonicas", "detail": "Stratum",
         "lat": 0.0, "lon": 0.01},
        {"ts": "2", "kind": "bio_analyse", "label": "Stratum Tectonicas", "detail": "Stratum",
         "lat": 0.0, "lon": 0.01},
        {"ts": "3", "kind": "bio_log", "label": "Bacterium Cerbrus", "detail": "Bacterium",
         "lat": 0.01, "lon": 0.0},
        {"ts": "4", "kind": "bio_analyse", "label": "Bacterium Cerbrus", "detail": "Bacterium",
         "lat": 0.01, "lon": 0.0},
        {"ts": "5", "kind": "codex", "label": "Crystalline Shards", "detail": "Shards",
         "lat": -0.01, "lon": 0.0},
    ]
    here = {"lat": 0.0, "lon": 0.0, "heading": 90}
    ok = compass_lines(here, lm, 400000.0, sig_bio=2, orbit=True)
    assert ok[0][0].startswith("KNOWN POINTS  bio 2 done"), ok
    lost = ["map", "bio:Stratum Tectonicas", "bio:Bacterium Cerbrus"]
    bad = compass_lines(here, lm, 400000.0, sig_bio=2, orbit=True, lost=lost)
    assert bad[0][0].startswith("KNOWN POINTS  bio 0 done, 2 lost - redo"), bad
    st_row = [ln for ln in bad if ln[0].startswith("Stratum Tecton LOST")]
    assert st_row and "brg 090 ^ ahead" in st_row[0][0], bad
    assert st_row[0][1] == "#FFB23E", st_row
    # one redo started: that species is open again (n/3), the other still lost
    lm.append({"ts": "6", "kind": "bio_log", "label": "Stratum Tectonicas",
               "detail": "Stratum", "lat": 0.0, "lon": 0.02})
    redo = compass_lines(here, lm, 400000.0, sig_bio=2, orbit=True, lost=lost)
    assert redo[0][0] == "KNOWN POINTS  bio 0 done, 1 open, 1 lost", redo   # 44 chars
    assert any(ln[0].startswith("Stratum Tectoni 1/3") for ln in redo), redo
    # the head never runs past 44 characters - what gives way, in order
    assert head_line("NAV", 2, signals=3) == "NAV  bio 2 done | 3 signals"
    h = head_line("KNOWN POINTS", 1, 1, 2, ["Bacterium", "Fungoida", "Stratum"], 5)
    assert h == "KNOWN POINTS  bio 1 done, 1 open, 2 lost", h
    h = head_line("NAV", 0, 0, 0, ["Bacterium", "Fungoida", "Stratum", "Tussock"])
    assert h == "NAV  bio 0 done | to find: Bacterium +3", h
    h = head_line("NAV", 0, 0, 1, ["Bacterium"])
    assert h == "NAV  bio 0 done, 1 lost - redo | 1 to find", h
    for args in [(3, 2, 4, ["Aleoida", "Bacterium", "Cactoida", "Clypeus", "Concha"], 9),
                 (12, 12, 12, ["Electricae"], None), (0, 0, 0, [], 1)]:
        for lb in ("NAV", "KNOWN POINTS"):
            assert len(head_line(lb, *args)) <= LINE_MAX, head_line(lb, *args)
    # a lost species without any position still shows in the head
    assert compass_lines(here, [], 400000.0, lost=["bio:Aleoida Gravis"])[0][0] \
        == "NAV  bio 0 done, 1 lost - redo"
    marks.append({"ts": "5", "kind": "embark", "label": "SRV", "detail": None,
                  "lat": 0.0, "lon": 0.0})
    assert body_state(marks)["parked"] is None
    # a new Log restarts the count
    marks.append({"ts": "6", "kind": "bio_log", "label": "Roseum Brain Tree",
                  "detail": "Brain Trees", "lat": 0.01, "lon": 0.0})
    assert body_state(marks)["species"][0]["samples"] == 1
    # the Rhino dropped from a hovering ship (no Touchdown): the ship flies
    # off at once and writes nothing - away until recalled (14.11.2026)
    rh = [{"ts": "2026-11-14T15:12:08Z", "kind": "srv_out", "label": "SRV Rhino", "detail": None,
           "lat": -26.05, "lon": 143.60}]
    st = body_state(rh)
    assert st["ship"] is None and st["ship_away"]["why"] == "hover", st
    t_launch = calendar.timegm(time.strptime("2026-11-14T15:12:08Z", "%Y-%m-%dT%H:%M:%SZ"))
    lines = compass_lines({"lat": -26.06, "lon": 143.61, "heading": 0}, rh, 492617.0, now=t_launch + 725)
    away = [ln for ln, _c in lines if ln.startswith("SHIP AWAY")]
    assert away == ["SHIP AWAY 12 min    flew off - recall it"], lines
    assert len(away[0]) <= 44
    assert not any("SHIP (hover)" in ln for ln, _c in lines), lines
    # flying the ship yourself: it is not away, whatever an old visit left
    aboard = compass_lines({"lat": -26.06, "lon": 143.61, "heading": 0, "mode": "ship"}, rh, 492617.0)
    assert not any(ln.startswith("SHIP AWAY") for ln, _c in aboard), aboard
    # docked back into the recalled ship: the ship is here again
    back = rh + [{"ts": "2026-11-14T15:42:12Z", "kind": "srv_in", "label": "SRV Rhino",
                  "detail": None, "lat": 0.0, "lon": 0.0}]
    assert body_state(back)["ship"] is None and body_state(back)["ship_away"] is None
    # on foot from the Rhino and back into it: the ship is still away
    foot = rh + [{"ts": "2026-11-14T15:20:00Z", "kind": "srv_parked", "label": "SRV", "detail": "SRV Rhino",
                  "lat": -26.0, "lon": 143.7},
                 {"ts": "2026-11-14T15:21:00Z", "kind": "embark", "label": "SRV", "detail": None,
                  "lat": -26.0, "lon": 143.7}]
    assert body_state(foot)["ship_away"]["why"] == "hover"
    # a Rhino out of a landed ship: the Touchdown stays the ship's point, nothing away
    td = [{"ts": "2026-11-14T15:00:00Z", "kind": "touchdown", "label": "b", "detail": "ship", "lat": 1.0, "lon": 2.0}]
    st = body_state(td + rh)
    assert st["ship"]["kind"] == "touchdown" and st["ship_away"] is None, st
    # the Nomad: the ship flies along - no point to show, nothing to recall
    st = body_state([{"ts": "1", "kind": "srv_out", "label": "Nomad", "detail": None,
                      "lat": 1.0, "lon": 1.0}])
    assert st["ship"] is None and st["ship_away"] is None
    # a landed ship sent away (Liftoff without the player): away - recall it
    gone = td + rh + [{"ts": "2026-11-14T15:13:00Z", "kind": "liftoff", "label": "b", "detail": "auto",
                       "lat": 1.0, "lon": 2.0}]
    st = body_state(gone)
    assert st["ship"] is None and st["ship_away"]["why"] == "dismissed", st
    assert any(ln.startswith("SHIP AWAY") and "dismissed - recall it" in ln
               for ln, _c in compass_lines({"lat": 1.0, "lon": 2.01, "heading": 0}, gone, 492617.0)), gone
    # you lift off yourself: aboard, nothing away
    assert body_state(td + [{"ts": "2026-11-14T15:13:00Z", "kind": "liftoff", "label": "b", "detail": "ship",
                             "lat": 1.0, "lon": 2.0}])["ship_away"] is None
    # the recalled ship lands (Touchdown without the player): its new point
    s = body_state(gone + [{"ts": "2026-11-14T15:30:00Z", "kind": "touchdown", "label": "b", "detail": "auto",
                            "lat": -26.2, "lon": 143.7}])
    assert s["ship"]["lat"] == -26.2 and s["ship"]["kind"] == "touchdown" and s["ship_away"] is None, s
    # nothing else on the body: the away line alone still shows
    only = compass_lines({"lat": 0.0, "lon": 0.0, "heading": 0}, rh, 492617.0)
    assert only and only[0][0] == "NAV" and only[1][0].startswith("SHIP AWAY"), only
    # Rhino rigs: tonnes close in time and place are one rig; numbered per launch

    def iso(sec):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1794330000 + sec))

    def ref(sec, lat, lon, label="Deuterium"):
        return {"ts": iso(sec), "kind": "refined", "label": label, "detail": "rig",
                "lat": lat, "lon": lon}

    rr = [{"ts": iso(10), "kind": "srv_out", "label": "SRV Rhino", "lat": 0.0, "lon": 0.0}]
    rr += [ref(100 + i, 0.0, 0.0001) for i in range(11)]
    rr.append(ref(105, 0.0, 0.0001, "Deuterium#1"))       # two in the same second
    rr += [ref(300 + i, 0.0005, 0.0008) for i in range(11)]
    rr.append(ref(312, 0.01, 0.0))                          # 2 s later but 4 km off
    rigs = body_state(rr, 492617.0)["rigs"]
    got = [(r["n"], r["tonnes"], r["type"]) for r in rigs]
    assert got == [(1, 12, "Deuterium"), (2, 11, "Deuterium"), (3, 1, "Deuterium")], got
    # without the radius only time splits
    assert [r["tonnes"] for r in body_state(rr)["rigs"]] == [12, 12]
    rr.append({"ts": iso(900), "kind": "srv_out", "label": "SRV Rhino", "lat": 0.0, "lon": 0.0})
    rr.append(ref(1000, 0.02, 0.0, "Gold"))
    last = body_state(rr, 492617.0)["rigs"][-1]
    assert (last["n"], last["type"], last["outing"]) == (1, "Gold", 2), last
    print("surfacenav selftest ok")


if __name__ == "__main__":
    _selftest()
