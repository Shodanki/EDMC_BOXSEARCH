// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// GAIN / LOSS (5.0) – what the active commander earned and spent, "like in
// real life": income, running costs and investment kept apart, per ship
// and for the commander, from the journal alone (fis/ledger.py).

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";
import { carrierMoneyRows } from "../carriermoney.js";
import { balancePane, outlookPane, segmentsPane, statementPane } from "../ledgerbook.js";

const SPANS = [[0, N_("all time")], [90, N_("90 days")], [30, N_("30 days")], [7, N_("7 days")], [1, N_("24 hours")]];
const LABEL = {
  income: { exobiology: N_("Exobiology"), exploration: N_("Exploration data"), codex: N_("Codex"),
    mining: N_("Mining (sold)"), trade: N_("Trade (profit)"), missions: N_("Missions"),
    rescue: N_("Search and rescue"), community_goals: N_("Community goals"), combat: N_("Bounties and bonds"),
    sales: N_("Sales (limpets, gear)"), other: N_("Other"), from_balance: N_("From the balance (missions and more)") },
  costs: { ship_loss: N_("Ship lost (rebuy)"), repairs: N_("Repairs"), fuel: N_("Fuel"),
    ammo: N_("Ammunition and vehicles"), limpets: N_("Limpets"), tritium: N_("Tritium"), crew: N_("Crew"), fines: N_("Fines"),
    other: N_("Other"), from_balance: N_("From the balance (not booked)") },
  invest: { ships: N_("Ships"), modules: N_("Modules"), transfers: N_("Transfers"), onfoot: N_("On-foot gear"),
    carrier: N_("Carrier") },
};

let root = null, data = null, busy = false, book = null;
let days = Number(localStorage.getItem("fis.ledger.days") || "0");
// GV1 (18.11.): the books of a company in sub-tabs - the overview stays first
const SUBS = [["overview", N_("OVERVIEW")], ["statement", N_("INCOME STATEMENT")], ["balance", N_("BALANCE SHEET")],
  ["segments", N_("SEGMENTS")], ["outlook", N_("OUTLOOK")]];
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* private window */ } return null; };
let sub = store("fis.ledger.sub") || "overview";
const bookState = { gran: store("fis.ledger.gran") || "month", idx: 0, seg: "all" };

export function mount(r) { root = r; root.classList.add("stat-view"); }

export async function update(ctx, reason) {
  if (!root || busy) return;
  if (reason !== "show" && reason !== "data" && data) return;
  busy = true;
  try { data = await getJSON("/api/ledger" + (days ? "?days=" + days : "")); } catch (e) { data = null; }
  if (sub !== "overview") await loadBook();
  else book = null;           // fetched again when a book tab is opened
  busy = false;
  render();
}

async function loadBook() {
  try { book = await getJSON("/api/ledger/statement"); } catch (e) { book = null; }
}

function tabs() {
  return el("div", { class: "kc-tabs st-tabs" }, ...SUBS.map(([k, label]) => el("button", { class: sub === k ? "on" : "",
    "aria-pressed": sub === k ? "true" : "false", "data-sub": k, text: t(label),
    onclick: async () => { sub = k; store("fis.ledger.sub", k); if (k !== "overview" && !book) await loadBook(); render(); } })));
}

function rerender() { store("fis.ledger.gran", bookState.gran); render(); }

function bookPane() {
  if (!book) return frame(t("GAIN / LOSS"), "", el("div", { class: "empty" }, t("Nothing booked in this period.")));
  if (sub === "statement") return statementPane(book, bookState, rerender);
  if (sub === "balance") return balancePane(book);
  if (sub === "segments") return segmentsPane(book, bookState, rerender);
  return outlookPane(book);
}

function cr(v, sign) {
  if (v === null || v === undefined) return "–";
  const s = sign && v > 0 ? "+ " : sign && v < 0 ? "− " : v < 0 ? "− " : "";
  const a = Math.abs(v);
  return s + (a >= 1e9 ? fmt(a / 1e9, 2) + " " + t("bn Cr") : a >= 1e6 ? fmt(a / 1e6, 1) + " M Cr" : fmt(a, 0) + " Cr");
}

function render() {
  if (!root) return;
  root.replaceChildren();
  const sel = el("select", { class: "lay-pick", onchange: (e) => {
    days = Number(e.target.value); localStorage.setItem("fis.ledger.days", String(days)); update(null, "data");
  } }, ...SPANS.map(([v, l]) => el("option", { value: String(v), text: t(l) })));
  sel.value = String(days);
  if (!SUBS.some(([k]) => k === sub)) sub = "overview";
  const head = withPopout(frame(t("GAIN / LOSS"), data && data.first ? t("journals since {d}", { d: new Date(data.first * 1000).toLocaleDateString() }) : "", [
    el("div", { class: "gal-row st-headrow" }, sub === "overview" ? el("span", { class: "c-dim", text: t("Period") }) : null,
      sub === "overview" ? sel : null, tabs()),
    el("div", { class: "c-dim small", text: t("Only the active commander. Booked from the journal to the ship flown at the time; what belongs to no ship is the commander's. \"From the balance\" is what the booked events do not explain - missions, or journals missing for a stretch.") }),
  ], { appear: false }), "ledger");
  if (sub !== "overview") {
    root.append(el("div", { class: "stat-wrap solo" }, el("div", { class: "stat-main" }, head, bookPane())));
    return;
  }
  if (!data || data.empty) {
    root.append(el("div", { class: "stat-wrap solo" }, el("div", { class: "stat-grid scroll" }, head,
      frame(t("BALANCE"), "", el("div", { class: "empty" }, t("Nothing booked in this period."))))));
    return;
  }
  root.append(el("div", { class: "stat-wrap" },
    el("div", { class: "stat-grid scroll" }, head, balance(), block("income", t("INCOME")), block("costs", t("RUNNING COSTS")),
      block("invest", t("INVESTMENT")), weeks()),
    el("div", { class: "stat-side scroll" }, open(), ships(), commander(), losses(), carrier())));
}

function row(label, value, cls) {
  return el("div", { class: "st-row" }, el("span", { class: "c-dim", text: label }), el("span", { class: "num " + (cls || ""), text: value }));
}

function balance() {
  const T = data.totals;
  const rows = [
    row(t("Income"), cr(T.income, true), "c-green"),
    row(t("Running costs"), cr(-T.costs, true), "c-amber"),
    row(t("Net"), cr(T.net, true), T.net >= 0 ? "c-green" : "c-red"),
    row(t("Investment (bought less sold)"), cr(-T.invest, true), "c-dim"),
    row(t("Net after investment"), cr(T.net - T.invest, true), T.net - T.invest >= 0 ? "c-green" : "c-red"),
  ];
  if (data.rest.gaps) rows.push(el("div", { class: "c-dim small", text: t("{n} times the balance moved more than the journal books: + {p} / − {m}.",
    { n: data.rest.gaps, p: cr(data.rest.plus), m: cr(data.rest.minus) }) }));
  return frame(t("BALANCE"), "", rows, { cls: "st-card", appear: false });
}

function block(kind, title) {
  const list = data.totals[{ income: "income_rows", costs: "cost_rows", invest: "invest_rows" }[kind]] || [];
  const out = list.map(r => el("div", { class: "st-row" + (r.key === "from_balance" ? " c-dim" : "") },
    el("span", { class: "c-dim", text: t(LABEL[kind][r.key] || r.key) }),
    el("span", { class: "num", text: cr(r.cr) }),
    el("span", { class: "num small c-dim", text: r.key === "from_balance" ? "~" : "×" + r.n })));
  if (!out.length) out.push(el("div", { class: "c-dim", text: t("none") }));
  return frame(title, "", out, { cls: "st-card", appear: false });
}

function weeks() {
  const W = data.weeks || [];
  if (!W.length) return null;
  const top = Math.max(1, ...W.map(w => Math.max(w.income, w.costs)));
  const rows = W.map(w => el("div", { class: "st-row" },
    el("span", { class: "c-dim small", text: w.week }),
    el("span", { class: "lbar" }, el("i", { style: { width: (100 * w.income / top) + "%" } })),
    el("span", { class: "num small", text: cr(w.income - w.costs, true) })));
  return frame(t("PER WEEK"), t("net"), rows, { cls: "st-card", appear: false });
}

function ships() {
  const rows = (data.ships || []).map(s => el("div", { class: "st-ship" },
    el("div", { class: s.current ? "c-cyan" : "" }, (s.name || s.type_name || s.type || "?") + (s.name && (s.type_name || s.type) ? " · " : ""),
      el("span", { class: "c-dim small", text: s.name ? (s.type_name || s.type || "") : "" }), s.current ? el("span", { class: "c-cyan small", text: " ◂ " + t("now") }) : null),
    row(t("Income"), cr(s.income), "c-green"), row(t("Running costs"), cr(s.costs), "c-amber"),
    s.invest ? row(t("Investment"), cr(s.invest), "c-dim") : null,
    row(t("Net"), cr(s.net, true), s.net >= 0 ? "c-green" : "c-red")));
  if (!rows.length) rows.push(el("div", { class: "c-dim", text: t("none") }));
  return frame(t("PER SHIP"), "", rows, { cls: "st-card", appear: false });
}

function commander() {
  const C = data.cmdr;
  if (!C.income && !C.costs && !C.invest) return null;
  const rows = [row(t("Income"), cr(C.income), "c-green"), row(t("Running costs"), cr(C.costs), "c-amber"),
    row(t("Investment"), cr(C.invest), "c-dim"),
    el("div", { class: "c-dim small", text: t("Not tied to a ship: community goals, crew, fines, stored modules, on-foot gear, the balance rest.") })];
  return frame(t("COMMANDER"), "", rows, { cls: "st-card", appear: false });
}

// B6: what is earned but not booked yet - unsold data, valued like UNSOLD DATA
function open() {
  const O = data.open;
  if (!O || (!O.bio_count && !O.systems)) return null;
  const rows = [];
  if (O.bio_count) rows.push(row(t("Exobiology (own prices)"), O.bio ? "~ " + cr(O.bio) : "–", "c-amber"));
  const V = O.explo;
  if (O.systems) rows.push(row(t("Exploration data"), V && V.est ? "~ " + cr(V.mid) + (V.calibrated ? " (" + cr(V.lo) + " – " + cr(V.hi) + ")" : "") : "–", "c-amber"));
  if (V && V.est) rows.push(el("div", { class: "c-dim small", text: V.calibrated ? t("from {n} sales", { n: V.n }) : t("(formula, not calibrated yet)") }));
  rows.push(el("div", { class: "c-dim small", text: t("Unsold, not booked yet: what the data would bring - and what a crash would cost.") }));
  return frame(t("OPEN"), "", rows, { cls: "st-card", appear: false });
}

function losses() {
  const D = data.deaths || [];
  if (!D.length) return null;
  const rows = D.map(d => row(new Date(d.ts * 1000).toLocaleDateString() + " · " + (d.ship || d.type_name || d.type || "?"),
    d.cost ? cr(d.cost) : t("no rebuy"), d.cost ? "c-red" : "c-dim"));
  return frame(t("SHIPS LOST"), "", rows, { cls: "st-card", appear: false });
}

function carrier() {
  const K = data.carrier;
  const U = K.upkeep;
  // CT2: Frontier's figures and the journal's, in one frame
  if (K.money) return frame(t("CARRIER"), K.money.frontier ? t("Frontier") : t("journal"), carrierMoneyRows(K.money), { cls: "st-card", appear: false });
  if (!K.deposit && !K.withdraw && !U) return null;
  const rows = [row(t("Paid in"), cr(K.deposit)), row(t("Taken out"), cr(K.withdraw))];
  // PL2: upkeep from the carrier's balance, your transfers taken out - an estimate
  if (U) rows.push(row(t("Upkeep (estimate)"), U.cost ? "~ " + cr(-U.cost, true) : t("not measurable"), U.cost ? "c-amber" : "c-dim"),
    el("div", { class: "c-dim small", text: t("From {n} balance readings over {d} days, your transfers taken out. Market income at the carrier cannot be told apart - so it can come out too low; not in the sums above.",
      { n: U.readings, d: fmt(U.days, 0) }) }));
  rows.push(el("div", { class: "c-dim small", text: t("Transfers move money, they are no gain or loss.") }));
  return frame(t("CARRIER"), "", rows, { cls: "st-card", appear: false });
}
