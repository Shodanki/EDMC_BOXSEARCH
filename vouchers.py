# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.1.0 ST13: bounty vouchers and combat bonds not redeemed yet - money the
commander has earned but loses with the ship, like unsold data. Shared by
the plugin's overlay (the RISK line) and the FIS (LEDGER > OPEN).

From the journal alone, per commander:

- Bounty (Rewards per faction, or Faction + Reward) adds bounty vouchers;
- FactionKillBond and CapShipBond add combat bonds (AwardingFaction);
- CodexEntry with a VoucherAmount adds a codex voucher (a new entry in a
  region - the explorer's kind);
- RedeemVoucher takes them off per faction (Factions list, or Faction);
  redeemed at Interstellar Factors (BrokerPercentage) it clears that kind;
- Died: everything not redeemed is lost (kept as the last loss).

Plain Python, read only, nothing online.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

__all__ = ["VoucherBook", "EVENTS"]

EVENTS = ("Bounty", "FactionKillBond", "CapShipBond", "CodexEntry", "RedeemVoucher", "Died", "LoadGame", "Commander")
KINDS = {"bounty": "bounty", "combatbond": "bonds", "codex": "codex"}
EMPTY = ("bounty", "bonds", "codex")


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


class VoucherBook:
    """What each commander holds unredeemed, fed journal events in order."""

    def __init__(self) -> None:
        self.loaded = False
        self._early: list = []                       # fed before load(): replayed after the history
        self.fid: Optional[str] = None
        self.held: Dict[Optional[str], Dict[str, Dict[str, float]]] = {}
        self.lost: Dict[Optional[str], Dict[str, Any]] = {}
        self.since: Dict[Optional[str], Optional[str]] = {}

    def _mine(self) -> Dict[str, Dict[str, float]]:
        return self.held.setdefault(self.fid, {k: {} for k in EMPTY})

    def _add(self, kind: str, faction: Any, cr: Any, ts: Optional[str]) -> None:
        cr = _num(cr)
        if cr <= 0:
            return
        h = self._mine()
        if not any(h.values()):
            self.since[self.fid] = ts
        f = str(faction or "?")
        h[kind][f] = h[kind].get(f, 0.0) + cr

    def load(self, history: Iterable[Dict[str, Any]]) -> None:
        """The plugin's start: the journal history (oldest first), then the
        live events that came meanwhile."""
        early, last = self._early, ""
        self.__init__()
        for e in history:
            self.feed(e)
            last = max(last, e.get("timestamp") or "")
        for e in early:
            if (e.get("timestamp") or "") > last:
                self.feed(e)
        self.loaded, self._early = True, []

    def feed_live(self, e: Dict[str, Any]) -> None:
        """A live journal event (kept for load() until the history is read)."""
        if e.get("event") in EVENTS:
            if not self.loaded:
                self._early.append(e)
            self.feed(e)

    def feed(self, e: Dict[str, Any]) -> None:
        """One journal event (others are ignored)."""
        ev = e.get("event")
        if ev in ("LoadGame", "Commander"):
            self.fid = e.get("FID") or self.fid
        elif ev == "Bounty":
            rewards = e.get("Rewards")
            if isinstance(rewards, list):
                for r in rewards:
                    if isinstance(r, dict):
                        self._add("bounty", r.get("Faction"), r.get("Reward"), e.get("timestamp"))
            else:
                self._add("bounty", e.get("Faction"), e.get("Reward") or e.get("TotalReward"), e.get("timestamp"))
        elif ev in ("FactionKillBond", "CapShipBond"):
            self._add("bonds", e.get("AwardingFaction"), e.get("Reward"), e.get("timestamp"))
        elif ev in ("CodexEntry", "CodexVoucher"):            # CodexVoucher: the FIS's slim copy
            self._add("codex", e.get("Region_Localised") or "Codex", e.get("VoucherAmount"), e.get("timestamp"))
        elif ev == "RedeemVoucher":
            self._redeem(e)
        elif ev == "Died":
            t = self.totals()
            t.pop("lost", None)
            if t["total"]:
                self.lost[self.fid] = dict(t, ts=e.get("timestamp"))
            self.held[self.fid] = {k: {} for k in EMPTY}

    def _redeem(self, e: Dict[str, Any]) -> None:
        kind = KINDS.get(str(e.get("Type") or "").lower())
        if kind is None:
            return
        h = self._mine()[kind]
        if e.get("BrokerPercentage") is not None or kind == "codex":   # Interstellar Factors / codex: all of it
            h.clear()
            return
        parts = e.get("Factions") if isinstance(e.get("Factions"), list) else [
            {"Faction": e.get("Faction"), "Amount": e.get("Amount")}]
        for p in parts:
            if not isinstance(p, dict):
                continue
            f = str(p.get("Faction") or "?")
            left = h.get(f, 0.0) - _num(p.get("Amount"))
            if left > 0.5:
                h[f] = left
            else:
                h.pop(f, None)

    def feed_all(self, events: Iterable[Dict[str, Any]]) -> "VoucherBook":
        """A whole journal history, in order."""
        for e in events:
            self.feed(e)
        return self

    def totals(self, fid: Any = "current") -> Dict[str, Any]:
        """{"bounty", "bonds", "codex", "total", "factions", "since", "lost"}
        of a commander (default: the one logged in last)."""
        k = self.fid if fid == "current" else fid
        h = self.held.get(k) or {}
        out: Dict[str, Any] = {kind: round(sum((h.get(kind) or {}).values())) for kind in EMPTY}
        out["total"] = sum(out[kind] for kind in EMPTY)
        out["factions"] = sorted(({"faction": f, "kind": kind, "cr": round(v)} for kind in EMPTY
                                  for f, v in (h.get(kind) or {}).items()), key=lambda x: -x["cr"])[:8]
        out["since"] = self.since.get(k) if out["total"] else None
        out["lost"] = self.lost.get(k)
        return out
