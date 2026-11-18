// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// 5.0 GV1: GAIN / LOSS as a free trader and mercenary company would close
// its books - income statement, balance sheet, segments, outlook, with
// their charts (fis/statement.py). Fictional, loosely after the German HGB;
// "~" marks what is estimated, "unknown" what no source states.

import { el, frame, fmt } from "./ui.js";
import { t, N_ } from "./i18n.js";

export const SEG = { exploration: N_("Exploration"), exobiology: N_("Exobiology"), mining: N_("Mining"), trade: N_("Trade"),
  combat: N_("Bounties and bonds"), missions: N_("Contracts and missions"), carrier: N_("Carrier"),
  unallocated: N_("Unallocated ship costs") };
const LINE = { revenue: N_("1. Revenue"), other_income: N_("2. Other operating income"), material: N_("3. Cost of materials"),
  personnel: N_("4. Personnel expenses"), write_downs: N_("5. Write-downs and losses"), other_costs: N_("6. Other operating expenses") };
const COST_SIDE = { material: true, personnel: true, write_downs: true, other_costs: true };
const ROW = { exploration: N_("Exploration data"), codex: N_("Codex"), exobiology: N_("Exobiology"), mining: N_("Mining (sold)"),
  trade: N_("Trade (gross sales)"), combat: N_("Bounties and bonds"), missions: N_("Missions"), rescue: N_("Search and rescue"),
  community_goals: N_("Community goals"), sales: N_("Sales (limpets, gear)"), other: N_("Other"),
  from_balance: N_("From the balance (not booked)"), cogs: N_("Cost of goods sold (trade)"), fuel: N_("Fuel"), ammo: N_("Ammunition and vehicles"), limpets: N_("Limpets"),
  tritium: N_("Tritium"), crew: N_("Wages of the NPC pilots"), carrier_services: N_("Carrier crew and services"),
  carrier_core: N_("Carrier core upkeep"), carrier_upkeep: N_("Carrier upkeep"), ship_loss: N_("Ships lost (rebuy)"),
  repairs: N_("Repairs"), fines: N_("Fines"), ships: N_("Ships"), modules: N_("Modules"), transfers: N_("Transfers"),
  onfoot: N_("On-foot gear"), carrier: N_("Carrier") };
const GRAN = [["week", N_("week")], ["month", N_("month")], ["year", N_("year")], ["all", N_("all time")]];
const BS = { ships: N_("Ships and their modules"), carrier: N_("Fleet carrier"), carrier_cargo: N_("Carrier cargo"),
  unsold_data: N_("Unsold data (claims)"), cash: N_("Credit balance"), carrier_bank: N_("Carrier bank"),
  upkeep_due: N_("Carrier upkeep still due this week"), orders_reserved: N_("Reserved for purchase orders") };

export function crBook(v, neg) {
  if (v === null || v === undefined) return t("unknown");
  const x = neg ? -v : v;
  const a = Math.abs(x);
  return (x < 0 ? "− " : "") + (a >= 1e9 ? fmt(a / 1e9, 2) + " " + t("bn Cr") : a >= 1e6 ? fmt(a / 1e6, 1) + " M Cr" : fmt(a, 0) + " Cr");
}
const mark = (est) => est ? "~ " : "";

// ------------------------------------------------------------------ SVG
const NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...kids) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
  for (const k of kids) if (k !== null && k !== undefined) n.append(typeof k === "string" ? document.createTextNode(k) : k);
  return n;
}

/** Waterfall: revenue and other income up, each cost block down, the result. */
export function waterfall(S) {
  const L = S.lines;
  const steps = [["revenue", L.revenue.cr], ["other_income", L.other_income.cr], ["material", -L.material.cr],
    ["personnel", -L.personnel.cr], ["write_downs", -L.write_downs.cr], ["other_costs", -L.other_costs.cr]];
  let run = 0, lo = 0, hi = 0;
  const bars = steps.map(([k, v]) => { const a = run; run += v; lo = Math.min(lo, a, run); hi = Math.max(hi, a, run); return [k, a, run, v]; });
  bars.push(["result", 0, run, run]);
  lo = Math.min(lo, run); hi = Math.max(hi, run);
  const W = 560, H = 190, top = 14, bot = 34, bw = W / bars.length;
  const y = (v) => top + (hi - v) / ((hi - lo) || 1) * (H - top - bot);
  const short = { revenue: N_("Revenue"), other_income: N_("Other income"), material: N_("Material"), personnel: N_("Personnel"),
    write_downs: N_("Losses"), other_costs: N_("Other costs"), result: N_("Result") };
  const g = bars.map(([k, a, b, v], i) => {
    const cls = k === "result" ? (v >= 0 ? "gv-res" : "gv-neg") : v >= 0 ? "gv-pos" : "gv-neg";
    const x = i * bw + 6, y0 = y(Math.max(a, b)), h = Math.max(1, Math.abs(y(a) - y(b)));
    return svg("g", {}, svg("rect", { x, y: y0, width: bw - 12, height: h, class: cls }),
      svg("text", { x: x + (bw - 12) / 2, y: H - bot + 14, class: "gv-lbl", "text-anchor": "middle" }, t(short[k])),
      svg("text", { x: x + (bw - 12) / 2, y: Math.max(10, y0 - 3), class: "gv-val", "text-anchor": "middle" }, crBook(v)));
  });
  return svg("svg", { viewBox: "0 0 " + W + " " + H, class: "gv-chart", role: "img", "aria-label": t("Waterfall of the income statement") },
    svg("line", { x1: 0, x2: W, y1: y(0), y2: y(0), class: "gv-axis" }), ...g);
}

/** Bars per segment, gains right and losses left of the zero line. */
export function segmentBars(rows) {
  const W = 560, rowH = 22, H = rows.length * rowH + 8, lab = 150;
  const max = Math.max(1, ...rows.map(r => Math.abs(r.net)));
  const neg = rows.some(r => r.net < 0), zero = neg ? lab + (W - lab) / 2 : lab;
  const span = neg ? (W - lab) / 2 - 70 : W - lab - 80;
  const g = rows.map((r, i) => {
    const w = Math.max(1, Math.abs(r.net) / max * span), yy = 4 + i * rowH;
    const x = r.net >= 0 ? zero : zero - w;
    return svg("g", {}, svg("text", { x: 0, y: yy + 14, class: "gv-lbl" }, t(SEG[r.seg] || r.seg)),
      svg("rect", { x, y: yy + 3, width: w, height: rowH - 8, class: r.net >= 0 ? "gv-pos" : "gv-neg" }),
      svg("text", { x: r.net >= 0 ? x + w + 4 : x - 4, y: yy + 14, class: "gv-val", "text-anchor": r.net >= 0 ? "start" : "end" },
        mark(r.est) + crBook(r.net)));
  });
  return svg("svg", { viewBox: "0 0 " + W + " " + H, class: "gv-chart", role: "img", "aria-label": t("Result per segment") },
    svg("line", { x1: zero, x2: zero, y1: 0, y2: H, class: "gv-axis" }), ...g);
}

/** The course of the credit balance and the carrier bank over time. */
export function wealthCourse(course) {
  const lines = [["cash", course.cash || [], "gv-l1", N_("Credit balance")], ["carrier", course.carrier || [], "gv-l2", N_("Carrier bank")]]
    .filter(([, p]) => p.length >= 2);
  if (!lines.length) return el("div", { class: "c-dim", text: t("Not enough balance readings yet.") });
  const all = lines.flatMap(([, p]) => p);
  const t0 = Math.min(...all.map(p => p[0])), t1 = Math.max(...all.map(p => p[0]));
  const v1 = Math.max(1, ...all.map(p => p[1])), v0 = Math.min(0, ...all.map(p => p[1]));
  const W = 560, H = 200, L = 6, B = 26, T = 10;
  const x = (ts) => L + (ts - t0) / ((t1 - t0) || 1) * (W - L - 8), y = (v) => T + (v1 - v) / ((v1 - v0) || 1) * (H - T - B);
  const paths = lines.map(([, p, cls]) => svg("polyline", { points: p.map(q => x(q[0]).toFixed(1) + "," + y(q[1]).toFixed(1)).join(" "), class: cls }));
  const d = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { month: "2-digit", year: "2-digit" });
  return el("div", {}, svg("svg", { viewBox: "0 0 " + W + " " + H, class: "gv-chart", role: "img", "aria-label": t("Course of wealth") },
    svg("line", { x1: L, x2: W, y1: y(0), y2: y(0), class: "gv-axis" }), ...paths,
    svg("text", { x: L, y: H - 8, class: "gv-lbl" }, d(t0)), svg("text", { x: W - 8, y: H - 8, class: "gv-lbl", "text-anchor": "end" }, d(t1)),
    svg("text", { x: W - 8, y: T + 8, class: "gv-val", "text-anchor": "end" }, crBook(v1))),
  el("div", { class: "gv-legend small" }, ...lines.map(([, p, cls, label]) => el("span", { class: cls + "-key" },
    "■ " + t(label) + " · " + crBook(p[p.length - 1][1])))));
}

// ------------------------------------------------------------------ statement
function cell(v, cost, est) { return el("td", { class: "num" + (v ? "" : " c-dim"), text: v ? mark(est) + crBook(v, cost) : "–" }); }

function statementTable(S, P) {
  const rows = [el("tr", {}, el("th", { text: "" }), el("th", { class: "num", text: S.label === "all" ? t("all time") : S.label }),
    el("th", { class: "num", text: P ? P.label : "" }))];
  for (const k of Object.keys(LINE)) {
    const a = S.lines[k], b = P ? P.lines[k] : null;
    const cost = !!COST_SIDE[k];
    rows.push(el("tr", { class: "gv-line" }, el("td", { text: t(LINE[k]) }), cell(a.cr, cost, a.est), P ? cell(b.cr, cost, b.est) : el("td")));
    const keys = [...new Set([...a.rows.map(r => r.key), ...(b ? b.rows.map(r => r.key) : [])])];
    for (const key of keys) {
      const ra = a.rows.find(r => r.key === key), rb = b ? b.rows.find(r => r.key === key) : null;
      rows.push(el("tr", { class: "gv-sub" }, el("td", { text: t(ROW[key] || SEG[key] || key) }),
        cell(ra ? ra.cr : 0, cost, ra && ra.est), P ? cell(rb ? rb.cr : 0, cost, rb && rb.est) : el("td")));
    }
  }
  rows.push(el("tr", { class: "gv-sum" }, el("td", { text: t("7. Operating result") }),
    el("td", { class: "num " + (S.result >= 0 ? "c-green" : "c-red"), text: mark(S.est) + crBook(S.result) }),
    P ? el("td", { class: "num " + (P.result >= 0 ? "c-green" : "c-red"), text: mark(P.est) + crBook(P.result) }) : el("td")));
  rows.push(el("tr", { class: "gv-sub" }, el("td", { text: t("Memo: investment (ships, modules, gear)") }),
    cell(S.invest, true), P ? cell(P.invest, true) : el("td")));
  return el("table", { class: "ns-tab gv-tab" }, ...rows);
}

/** INCOME STATEMENT: period picker, the statement with the period before, the waterfall. */
export function statementPane(B, state, rerender) {
  const list = state.gran === "all" ? [B.statements.all] : B.statements[state.gran] || [];
  const i = Math.min(state.idx || 0, Math.max(0, list.length - 1));
  const S = list[i], P = state.gran === "all" ? null : list[i + 1] || null;
  const gsel = el("select", { class: "lay-pick", onchange: (e) => { state.gran = e.target.value; state.idx = 0; rerender(); } },
    ...GRAN.map(([v, l]) => el("option", { value: v, text: t(l) })));
  gsel.value = state.gran;
  const psel = state.gran === "all" ? null : el("select", { class: "lay-pick", onchange: (e) => { state.idx = Number(e.target.value); rerender(); } },
    ...list.map((s, j) => el("option", { value: String(j), text: s.label + (s.running ? " · " + t("running") : "") })));
  if (psel) psel.value = String(i);
  const memo = state.gran === "all" && B.carrier_memo ? el("div", { class: "c-dim small", text: t("Memo, not in the result: the carrier's market earned {m} and its bar {b} in all (Frontier) - into the carrier bank.",
    { m: crBook(B.carrier_memo.market_profit), b: crBook(B.carrier_memo.bar_profit) }) }) : null;
  const left = frame(t("INCOME STATEMENT"), t("after § 275 HGB, fictional"), [
    el("div", { class: "gal-row" }, el("span", { class: "c-dim", text: t("Period") }), gsel, psel),
    el("div", { class: "c-cyan small", text: t("Free trader and mercenary company of the commander · books closed from the journal") }),
    S ? statementTable(S, P) : el("div", { class: "c-dim", text: t("Nothing booked in this period.") }), memo,
    el("div", { class: "c-dim small", text: t("~ estimated: the carrier's upkeep from its balance (PL2) over {d} days of the period, split into crew and core as Frontier bills it. Audit: none - no auditor of the Pilots' Federation has seen these books.",
      { d: S && S.upkeep_days !== null && S.upkeep_days !== undefined ? fmt(S.upkeep_days, 0) : "–" }) }),
  ], { cls: "st-card", appear: false });
  const right = S ? frame(t("WATERFALL"), S.label === "all" ? t("all time") : S.label, [waterfall(S)], { cls: "st-card", appear: false }) : null;
  return cols([left], [right]);
}

function cols(...c) {
  const built = c.map(x => x.filter(Boolean)).filter(x => x.length);
  return el("div", { class: "st-pane st-pane-book scroll" }, el("div", { class: "st-cols", style: "--n: " + built.length },
    ...built.map(x => el("div", { class: "st-col" }, ...x))));
}

// ------------------------------------------------------------------ balance sheet
function bsRows(items) {
  return items.map(x => el("tr", {}, el("td", { text: t(BS[x.key] || x.key) + (x.n ? " (" + x.n + ")" : "") }),
    el("td", { class: "num" + (x.cr === null ? " c-dim" : ""), text: x.cr === null ? t("unknown") : mark(x.est) + crBook(x.cr) })));
}

export function balancePane(B) {
  const S = B.balance_sheet;
  const sum = (label, v, cls) => el("tr", { class: "gv-sum" }, el("td", { text: label }), el("td", { class: "num " + (cls || ""), text: crBook(v) }));
  const assets = frame(t("ASSETS"), t("after § 266 HGB, fictional"), [el("table", { class: "ns-tab gv-tab" },
    el("tr", { class: "gv-line" }, el("td", { text: t("A. Fixed assets") }), el("td")), ...bsRows(S.fixed),
    el("tr", { class: "gv-line" }, el("td", { text: t("B. Current assets") }), el("td")), ...bsRows(S.current),
    sum(t("Total assets"), S.assets))], { cls: "st-card", appear: false });
  const liab = frame(t("EQUITY AND LIABILITIES"), "", [el("table", { class: "ns-tab gv-tab" },
    el("tr", { class: "gv-line" }, el("td", { text: t("A. Equity (fictional: the rest)") }), el("td", { class: "num", text: crBook(S.equity) })),
    el("tr", { class: "gv-line" }, el("td", { text: t("B. Provisions") }), el("td")), ...bsRows(S.provisions),
    sum(t("Total equity and liabilities"), S.liabilities))], { cls: "st-card", appear: false });
  const notes = frame(t("NOTES"), "", [
    el("div", { class: "c-dim small", text: t("Ships at the value the game states (fitting or hangar list): ~, what a sale would bring is less.") }),
    el("div", { class: "c-dim small", text: t("Unsold data at the value UNSOLD DATA estimates: ~.") }),
    S.unknown.length ? el("div", { class: "c-amber small", text: t("Not in the sums, no source: {k}.", { k: S.unknown.map(k => t(BS[k] || k)).join(", ") }) }) : null,
    el("div", { class: "c-dim small", text: t("No debts: the company owes nobody - equity is assets less provisions.") }),
  ], { cls: "st-card", appear: false });
  return cols([assets, notes], [liab]);
}

// ------------------------------------------------------------------ segments
export function segmentsPane(B, state, rerender) {
  const key = state.seg === "recent" ? "recent" : "all";
  const rows = B.segments[key] || [];
  const pick = el("select", { class: "lay-pick", onchange: (e) => { state.seg = e.target.value; rerender(); } },
    el("option", { value: "all", text: t("all time") }), el("option", { value: "recent", text: t("last 30 days") }));
  pick.value = key;
  const head = el("tr", {}, ...[t("segment"), t("revenue"), t("cost of goods"), t("own costs"), t("ship costs"), t("result"), t("hours"), t("Cr / h")]
    .map((h, i) => el("th", { class: i ? "num" : "", text: h })));
  const body = rows.map(r => el("tr", { class: r.seg === "unallocated" ? "gv-sub" : "" }, el("td", { text: t(SEG[r.seg] || r.seg) }),
    cell(r.revenue, false), cell(r.cogs, true), cell(r.costs, true, r.seg === "carrier" && r.costs && r.est),
    cell(r.ship_costs, true, r.seg !== "unallocated"),
    el("td", { class: "num " + (r.net >= 0 ? "c-green" : "c-red"), text: mark(r.est) + crBook(r.net) }),
    el("td", { class: "num", text: r.hours ? "~ " + fmt(r.hours, 1) : "–" }),
    el("td", { class: "num", text: r.per_hour !== null ? "~ " + crBook(r.per_hour) : "–" })));
  // best and worst: only real segments, not what no segment got
  const real = rows.filter(r => r.seg !== "unallocated");
  const best = real[0], worst = real[real.length - 1];
  const sel = frame(t("SEGMENTS"), "", [el("div", { class: "gal-row" }, el("span", { class: "c-dim", text: t("Period") }), pick),
    rows.length ? el("table", { class: "ns-tab gv-tab" }, head, ...body) : el("div", { class: "c-dim", text: t("Nothing booked in this period.") }),
    best ? el("div", { class: "st-row" }, el("span", { class: "c-dim", text: t("Best segment") }), el("span", { class: "c-green", text: t(SEG[best.seg]) + " · " + mark(best.est) + crBook(best.net) })) : null,
    worst && worst !== best ? el("div", { class: "st-row" }, el("span", { class: "c-dim", text: worst.net < 0 ? t("Where money goes in") : t("Weakest segment") }),
      el("span", { class: worst.net < 0 ? "c-red" : "c-amber", text: t(SEG[worst.seg]) + " · " + mark(worst.est) + crBook(worst.net) })) : null,
    el("div", { class: "c-dim small", text: t("Time (~): what follows an event of the segment (a jump, a scan, a prospected rock, a trade, a mission, carrier management) until the next, pauses over 15 minutes left out.") }),
    el("div", { class: "c-dim small", text: t("Ship costs (~): every running cost of a ship (fuel, repairs, ammunition and vehicles, limpets, a ship lost, other) goes to the segment you mainly ran with that ship in that session - more than half its activity time. Without such a segment it stays unallocated. The income statement keeps its totals; this only splits them.") }),
    el("div", { class: "c-dim small", text: t("Cost of goods: what was paid for the goods sold in trade. Own costs: tritium and the upkeep (~) of the carrier. Ships bought are investment, outside the result.") }),
  ], { cls: "st-card", appear: false });
  const chart = rows.length ? frame(t("RESULT PER SEGMENT"), key === "all" ? t("all time") : t("last 30 days"), [segmentBars(rows)], { cls: "st-card", appear: false }) : null;
  return cols([sel], [chart]);
}

// ------------------------------------------------------------------ outlook
function oRow(label, value, cls, note) {
  return el("div", { class: "st-row" }, el("span", { class: "c-dim", text: label }), el("span", { class: "num " + (cls || ""), text: value }),
    note ? el("span", { class: "num small c-dim", text: note }) : null);
}
const day = (ts) => new Date(ts * 1000).toLocaleDateString();

export function outlookPane(B) {
  const O = B.outlook, R = O.run;
  const rows = [];
  if (O.carrier_per_week) {
    const exact = O.carrier_source === "frontier";
    rows.push(oRow(t("Carrier upkeep per week"), (exact ? "" : "~ ") + crBook(O.carrier_per_week, true), "c-amber", exact ? t("Frontier") : t("estimate")));
    rows.push(oRow(t("Carrier available"), crBook(O.carrier_available)));
    rows.push(oRow(t("Carrier financed until"), O.carrier_until ? day(O.carrier_until) : t("unknown"),
      O.carrier_weeks < 8 ? "c-red" : O.carrier_weeks < 26 ? "c-amber" : "c-green", O.carrier_weeks ? t("{w} weeks", { w: fmt(O.carrier_weeks, 0) }) : ""));
    rows.push(oRow(t("Money must come in by"), O.carrier_until ? day(O.carrier_until) : t("unknown"), "", t("then the carrier bank is empty")));
  } else if (O.carrier_source === null && O.carrier_available !== null && O.carrier_available !== undefined) {
    rows.push(oRow(t("Carrier upkeep per week"), t("unknown")));
  }
  if (R.income !== null) {
    rows.push(el("div", { class: "c-cyan small st-learn-h", text: t("RUN RATE {a} – {b} ({p} of {n} weeks played)", { a: R.from, b: R.to, p: R.played, n: R.weeks }) }));
    rows.push(oRow(t("Income per week"), crBook(R.income), "c-green"));
    rows.push(oRow(t("Running costs per week"), crBook(R.costs, true), "c-amber"));
    rows.push(oRow(t("Weekly burn with the carrier"), crBook(O.burn, true), "c-amber"));
    rows.push(oRow(t("Covered by income"), O.coverage !== null ? fmt(O.coverage, 0) + " %" : "–", O.coverage >= 100 ? "c-green" : "c-red"));
    rows.push(oRow(t("Net per week"), crBook(O.net_run), O.net_run >= 0 ? "c-green" : "c-red"));
    if (O.cash_weeks) rows.push(oRow(t("Your credits last"), t("{w} weeks", { w: fmt(O.cash_weeks, 0) }), "c-red", t("at this run rate")));
  } else rows.push(el("div", { class: "c-dim", text: t("No run rate yet: the last four weeks are not in your journals.") }));
  const D = O.decommission;
  rows.push(el("div", { class: "c-cyan small st-learn-h", text: t("DECOMMISSION") }));
  if (D && !D.cancelled) rows.push(oRow(t("Refund the game named"), crBook(D.refund), "c-amber", day(D.ts)));
  else if (D) rows.push(oRow(t("Refund the game named"), crBook(D.refund), "c-dim", t("request cancelled")));
  else rows.push(oRow(t("Refund"), t("unknown"), "c-dim"));
  rows.push(el("div", { class: "c-dim small", text: D ? t("From the journal (CarrierDecommission, ScrapRefund).")
    : t("The game names the refund only when a decommission is requested (CarrierDecommission) - not before, so it stays unknown here.") }));
  const left = frame(t("OUTLOOK"), "", rows, { cls: "st-card", appear: false });
  const right = frame(t("COURSE OF WEALTH"), "", [wealthCourse(B.course),
    el("div", { class: "c-dim small", text: t("Credit balance where the game states it (login, carrier transfers); carrier bank from its readings (CarrierStats).") })],
  { cls: "st-card", appear: false });
  return cols([left], [right]);
}
