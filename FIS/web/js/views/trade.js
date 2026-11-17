// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// TRADE (5.0, HD1) – per commodity what your own sales fetched (average,
// range, number of sales), the galactic mean from the last market opened as
// a comparison, and – only while docked – what this market pays now
// (fis/trade.py). The hold and mined goods come first.

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t } from "../i18n.js";

let root = null, data = null, busy = false;

export function mount(r) { root = r; root.classList.add("stat-view"); }

export async function update(ctx, reason) {
  if (!root || busy) return;
  if (reason !== "show" && reason !== "data" && reason !== "status" && data) return;
  busy = true;
  try { data = await getJSON("/api/trade"); } catch (e) { data = null; }
  busy = false;
  render();
}

const day = (ts) => ts ? new Date(ts * 1000).toLocaleDateString() : "?";

function render() {
  if (!root) return;
  root.replaceChildren();
  const rows = (data && data.rows) || [];
  const M = data && data.market;
  const head = el("tr", {}, ...[t("commodity"), t("in hold"), t("your sales"), t("galactic mean"), t("this market pays")]
    .map(h => el("th", { text: h })));
  const body = rows.map(r => {
    const s = r.sold;
    return el("tr", { class: r.hold ? "c-cyan" : "" },
      el("td", { text: (r.mined || (s && s.own) ? "⛏ " : "") + r.name }),
      el("td", { class: "num", text: r.hold ? fmt(r.hold, 0) + " t" : "–" }),
      el("td", { class: "num" + (s ? "" : " c-dim"), text: s ? t("~{p} Cr/t ({lo}–{hi}, {n} sales, {t} t)",
        { p: fmt(s.avg, 0), lo: fmt(s.lo, 0), hi: fmt(s.hi, 0), n: s.sales, t: fmt(s.t, 0) }) : t("not sold yet") }),
      el("td", { class: "num c-dim", text: r.mean ? fmt(r.mean, 0) + " Cr/t" : "–" }),
      el("td", { class: "num" + (r.here && r.here.demand ? " c-green" : " c-dim"), text: r.here
        ? (r.here.demand ? t("{p} Cr/t · demand {d}", { p: fmt(r.here.price, 0), d: fmt(r.here.demand, 0) }) : t("no demand here")) : "–" }));
  });
  const notes = [
    el("div", { class: "c-dim small", text: t("Your own sales of the active commander (MarketSell); ⛏ mined or collected, not bought. Hold and mined goods first.") }),
    M ? el("div", { class: "c-dim small", text: t("Galactic mean from the last market you opened ({s}, {d}) - a comparison, not an offer.",
      { s: M.station || "?", d: day(M.ts) }) }) : null,
    el("div", { class: "small " + (data && data.docked_here ? "c-green" : "c-dim"), text: data && data.docked_here && M
      ? t("Docked at {s}: what this market pays now.", { s: M.station || "?" }) : t("Offers only while docked, after opening the commodity market.") }),
  ];
  const table = rows.length ? el("div", { class: "scroll" }, el("table", { class: "mine-table trade-table" }, head, ...body))
    : el("div", { class: "empty", text: t("Nothing sold, mined or carried yet.") });
  root.append(el("div", { class: "stat-wrap solo" }, el("div", { class: "stat-grid scroll trade-grid" },
    withPopout(frame(t("TRADE"), rows.length ? String(rows.length) : "", [table, ...notes], { appear: false }), "trade"))));
}
