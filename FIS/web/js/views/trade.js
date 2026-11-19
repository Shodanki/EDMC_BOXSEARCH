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
import { t, N_ } from "../i18n.js";

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

// h-tab (17.11.): one value per column with a plain heading, the range dim
// under nothing else, the galactic mean kept from every market that had one,
// your price against it in %; the totals in the frame's tag
const cr = (v) => v === null || v === undefined ? "–" : fmt(v, 0);
const ME = new Set(["commodity"]);

function cells(r) {
  const s = r.sold, vs = r.vs_mean;
  const mf = r.mean_from;
  return [
    el("td", { text: (r.mined || (s && s.own) ? "⛏ " : "") + r.name }),
    el("td", { class: "num", text: r.hold ? fmt(r.hold, 0) + " t" : "–" }),
    el("td", { class: "num" + (s ? " c-cyan" : " c-dim"), text: s ? cr(s.avg) : "–" }),
    el("td", { class: "num c-dim", text: s ? (s.lo === s.hi ? "" : cr(s.lo) + "–" + cr(s.hi)) : "" }),
    el("td", { class: "num", text: s ? fmt(s.sales, 0) : "–" }),
    el("td", { class: "num", text: s ? fmt(s.t, 0) + " t" : "–" }),
    el("td", { class: "num", text: s ? cr(s.cr) : "–" }),
    el("td", { class: "num c-dim", text: r.mean ? cr(r.mean) : "–",
      title: mf ? t(mf.edd ? "from {s}, {d} (EDDiscovery archive)" : "from {s}, {d}", { s: mf.station || "?", d: day(mf.ts) })
        : t("open a station's commodity market once (or switch on the EDDiscovery archive in the settings)") }),
    el("td", { class: "num " + (vs === null || vs === undefined ? "c-dim" : vs >= 0 ? "c-green" : vs < -10 ? "c-amber" : ""),
      text: vs === null || vs === undefined ? "–" : (vs > 0 ? "+" : "") + vs + " %" }),
    el("td", { class: "num" + (r.here && r.here.demand ? " c-green" : " c-dim"), text: r.here
      ? (r.here.demand ? t("{p} Cr/t · demand {d}", { p: fmt(r.here.price, 0), d: fmt(r.here.demand, 0) }) : t("no demand here")) : "–" }),
  ];
}

function render() {
  if (!root) return;
  root.replaceChildren();
  const rows = (data && data.rows) || [];
  const M = data && data.market;
  const heads = [[N_("commodity"), ""], [N_("in hold"), ""], [N_("your price"), "Cr/t"], [N_("range"), "Cr/t"], [N_("sales"), ""],
    [N_("sold"), ""], [N_("earned"), "Cr"], [N_("galactic mean"), "Cr/t"], [N_("you vs mean"), ""], [N_("this market pays"), ""]];
  const head = el("tr", {}, ...heads.map(([h, u]) => el("th", { class: ME.has(h) ? "" : "num", text: t(h) + (u ? " (" + u + ")" : "") })));
  const notes = [
    el("div", { class: "c-dim small", text: t("Your own sales of the active commander (MarketSell); ⛏ mined or collected, not bought. Hold and mined goods first.") }),
    el("div", { class: "c-dim small", text: t("Galactic mean: kept from every station market you opened ({n} commodities so far; fleet carriers have none) - a comparison, not an offer. Hover for where and when.",
      { n: data ? data.means || 0 : 0 }) }),
    el("div", { class: "small " + (data && data.docked_here ? "c-green" : "c-dim"), text: data && data.docked_here && M
      ? t("Docked at {s}: what this market pays now.", { s: M.station || "?" }) : t("Offers only while docked, after opening the commodity market.") }),
  ];
  const table = rows.length ? el("div", { class: "scroll" }, el("table", { class: "mine-table trade-table" }, head,
    ...rows.map(r => el("tr", { class: r.hold ? "trade-hold" : "" }, ...cells(r)))))
    : el("div", { class: "empty", text: t("Nothing sold, mined or carried yet.") });
  const tag = rows.length ? t("{n} commodities · {e} Cr from {s} sales", { n: rows.length, e: cr(data.earned), s: fmt(data.sales || 0, 0) }) : "";
  root.append(el("div", { class: "stat-wrap solo" }, el("div", { class: "stat-grid scroll trade-grid" },
    withPopout(frame(t("TRADE"), tag, [table, ...notes], { appear: false }), "trade"))));
}
