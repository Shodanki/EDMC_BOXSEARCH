# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
ST13 (5.1.0, user 25.11.): bounty vouchers, combat bonds and codex vouchers
not redeemed yet (vouchers.py) - earned per faction, redeemed per faction or
all at Interstellar Factors, lost at a death, per commander; the history read
at start with the live events that came meanwhile; the overlay's RISK line
names them, within 44 characters.

    python tests/vouchers.py      (from the plugin folder)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import cockpitinfo, situation, state, vouchers  # noqa: E402
from SHBOXSEARCH.sysdb import CMDR_READY, SystemDB  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


def e(ev, minute, **kw):
    return dict(kw, event=ev, timestamp="2027-02-01T10:%02d:00Z" % minute)


print("earned, redeemed, lost")
H = [e("LoadGame", 0, FID="F1"),
     e("Bounty", 1, Rewards=[{"Faction": "Alpha", "Reward": 50000}, {"Faction": "Beta", "Reward": 20000}],
       TotalReward=70000),
     e("Bounty", 2, Faction="Alpha", Reward=10000),                      # the older single form (skimmers)
     e("FactionKillBond", 3, AwardingFaction="Gamma", Reward=30000),
     e("CodexEntry", 4, Region_Localised="Inner Orion Spur", VoucherAmount=2500),
     e("CodexEntry", 5, Region_Localised="Inner Orion Spur")]           # known entry: no voucher
b = vouchers.VoucherBook().feed_all(H)
t = b.totals()
check((t["bounty"], t["bonds"], t["codex"], t["total"]) == (80000, 30000, 2500, 112500), "held: %s" % t)
check(t["factions"][0] == {"faction": "Alpha", "kind": "bounty", "cr": 60000}, "largest first, per faction")
check(t["since"] == "2027-02-01T10:01:00Z", "since the first one not redeemed")
b.feed(e("RedeemVoucher", 6, Type="bounty", Amount=60000, Factions=[{"Faction": "Alpha", "Amount": 60000}]))
check(b.totals()["bounty"] == 20000, "Alpha redeemed at its station, Beta still held")
b.feed(e("RedeemVoucher", 7, Type="CombatBond", Amount=22500, BrokerPercentage=25.0,
         Factions=[{"Faction": "", "Amount": 22500}]))
check(b.totals()["bonds"] == 0, "Interstellar Factors: all bonds gone")
b.feed(e("Died", 8))
t = b.totals()
check(t["total"] == 0 and t["lost"]["total"] == 22500 and t["lost"]["ts"] == "2027-02-01T10:08:00Z",
      "a death: the rest lost and remembered (%s)" % t["lost"])
b.feed(e("LoadGame", 9, FID="F2"))
check(b.totals()["total"] == 0 and b.totals("F1")["lost"]["total"] == 22500, "each commander their own")

print("the plugin's start: history first, then what came meanwhile")
vb = vouchers.VoucherBook()
vb.feed_live(e("Bounty", 30, Faction="Delta", Reward=5000))               # live, before the history is read
vb.feed_live(e("Music", 30))
vb.load(H)
check(vb.loaded and vb.totals()["bounty"] == 85000, "history + the live bounty: %s" % vb.totals()["bounty"])
vb.load(H + [e("Bounty", 30, Faction="Delta", Reward=5000)])
check(vb.totals()["bounty"] == 80000 + 5000, "a live event already in the history is not counted twice")

print("the RISK line")
lines = situation.risk_lines({}, "interdicted", {"bounty": 85000, "bonds": 0, "codex": 2500, "total": 87500})
check([x for x, _c in lines] == ["RISK  interdicted - at stake ~88 k Cr", "      vouchers: bounties 85 k · codex 2,500"]
      or lines[0][0].startswith("RISK  interdicted - at stake"), "vouchers alone light it: %s" % lines)
check(any(x.startswith("      vouchers: bounties") for x, _c in lines), "the kinds named")
both = situation.risk_lines({"bodies": 3, "systems": 1, "value": 1_000_000}, "hull 40 %",
                            {"bounty": 0, "bonds": 0, "codex": 0, "total": 0})
check(len(both) == 2 and "vouchers" not in both[-1][0], "no vouchers: the data line only")
check(situation.risk_lines({}, "x", None) == [], "nothing at stake: nothing")
check(all(len(x) <= situation.LINE_MAX for x, _c in lines + both), "every line within 44 characters")

print("fed by the hook")
state.ST.db = SystemDB(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
state.ST.db.set_meta(CMDR_READY, "test")
plugin_pkg.use_settings({})
cockpitinfo.VOUCHERS = vouchers.VoucherBook()
cockpitinfo.VOUCHERS.load([])
load.journal_entry("Cmdr", False, "", "", e("LoadGame", 40, FID="F42", Commander="Cmdr"), {"FID": "F42"})
load.journal_entry("Cmdr", False, "", "", e("FactionKillBond", 41, AwardingFaction="Gamma", Reward=12000),
                   {"FID": "F42"})
check(cockpitinfo.VOUCHERS.totals()["bonds"] == 12000, "a bond from the journal hook")

print("%d failure(s)" % fails)
sys.exit(1 if fails else 0)
