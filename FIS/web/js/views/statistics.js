// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// STATISTICS – the game's own record of the commander (the Statistics event
// written at every login), research first: ranks with progress, exploration,
// exobiology, mining, the carrier, wealth - and the growth over a chosen
// period (the Statistics event from back then against the latest one).

import { getJSON, postJSON } from "../api.js";
import { el, frame, fmt, meter, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";
import { carrierMoneyRows } from "../carriermoney.js";

const SPANS = [[0, N_("all time")], [90, N_("90 days")], [30, N_("30 days")], [7, N_("7 days")], [1, N_("24 hours")]];
const RANK_LABEL = { Explore: N_("Exploration"), Exobiologist: N_("Exobiology"), Trade: N_("Trade"),
  Combat: N_("Combat"), Soldier: N_("Mercenary"), CQC: N_("CQC"), Empire: N_("Empire"), Federation: N_("Federation") };
const REP_LABEL = { Federation: N_("Federation"), Empire: N_("Empire"), Alliance: N_("Alliance"), Independent: N_("Independent") };
// kinds: n number · cr credits · ly · t tonnes · h seconds as hours · km metres as km
const CARDS = [
  ["EXPLORATION", N_("EXPLORATION"), [
    ["Exploration", "Systems_Visited", N_("systems visited"), "n"],
    ["Exploration", "Total_Hyperspace_Jumps", N_("hyperspace jumps"), "n"],
    ["Exploration", "Total_Hyperspace_Distance", N_("hyperspace distance"), "ly"],
    ["derived", "avg_jump", N_("average jump"), "ly1"],
    ["Exploration", "Greatest_Distance_From_Start", N_("greatest distance from start"), "ly"],
    ["Exploration", "Planets_Scanned_To_Level_3", N_("bodies scanned"), "n"],
    ["Exploration", "Efficient_Scans", N_("efficient surface maps"), "n"],
    ["Exploration", "First_Footfalls", N_("first footfalls"), "n"],
    ["Exploration", "Planet_Footfalls", N_("planet footfalls"), "n"],
    ["Exploration", "OnFoot_Distance_Travelled", N_("on foot"), "km"],
    ["Exploration", "Exploration_Profits", N_("exploration data sold"), "cr"],
    ["Exploration", "Highest_Payout", N_("highest payout"), "cr"],
  ]],
  ["EXOBIOLOGY", N_("EXOBIOLOGY"), [
    ["Exobiology", "Organic_Genus_Encountered", N_("genera encountered"), "n"],
    ["Exobiology", "Organic_Species_Encountered", N_("species encountered"), "n"],
    ["Exobiology", "Organic_Variant_Encountered", N_("variants encountered"), "n"],
    ["Exobiology", "Organic_Systems", N_("systems with life"), "n"],
    ["Exobiology", "Organic_Planets", N_("planets with life"), "n"],
    ["Exobiology", "Organic_Data", N_("analyses sold"), "n"],
    ["Exobiology", "Organic_Data_Profits", N_("earned"), "cr"],
    ["Exobiology", "First_Logged", N_("first logged"), "n"],
    ["Exobiology", "First_Logged_Profits", N_("first logged bonus"), "cr"],
  ]],
  ["MINING", N_("MINING"), [
    ["Mining", "Quantity_Mined", N_("tonnes mined"), "t"],
    ["Mining", "Materials_Collected", N_("materials collected"), "n"],
    ["Mining", "Mining_Profits", N_("earned"), "cr"],
  ]],
  ["CARRIER", N_("CARRIER"), [
    ["FLEETCARRIER", "FLEETCARRIER_TOTAL_JUMPS", N_("jumps"), "n"],
    ["FLEETCARRIER", "FLEETCARRIER_DISTANCE_TRAVELLED", N_("distance travelled"), "ly"],
    ["FLEETCARRIER", "FLEETCARRIER_EXPORT_TOTAL", N_("goods sold"), "t"],
    ["FLEETCARRIER", "FLEETCARRIER_IMPORT_TOTAL", N_("goods bought"), "t"],
    ["FLEETCARRIER", "FLEETCARRIER_TRADEPROFIT_TOTAL", N_("market income"), "cr"],
    ["FLEETCARRIER", "FLEETCARRIER_VOUCHERS_PROFIT", N_("vouchers redeemed"), "cr"],
    ["FLEETCARRIER", "FLEETCARRIER_REFUEL_TOTAL", N_("refuels"), "n"],
    ["FLEETCARRIER", "FLEETCARRIER_REARM_TOTAL", N_("rearms"), "n"],
    ["FLEETCARRIER", "FLEETCARRIER_REPAIRS_TOTAL", N_("repairs"), "n"],
  ]],
  ["WEALTH", N_("WEALTH & TIME"), [
    ["Bank_Account", "Current_Wealth", N_("wealth"), "cr"],
    ["Exploration", "Time_Played", N_("time played"), "h"],
    ["Bank_Account", "Owned_Ship_Count", N_("ships owned"), "n"],
    ["Bank_Account", "Spent_On_Ships", N_("spent on ships"), "cr"],
    ["Bank_Account", "Spent_On_Outfitting", N_("spent on outfitting"), "cr"],
    ["Bank_Account", "Spent_On_Repairs", N_("spent on repairs"), "cr"],
    ["Bank_Account", "Spent_On_Fuel", N_("spent on fuel"), "cr"],
    ["Bank_Account", "Spent_On_Insurance", N_("spent on insurance"), "cr"],
    ["Bank_Account", "Insurance_Claims", N_("insurance claims"), "n"],
    ["Crew", "NpcCrew_TotalWages", N_("crew wages"), "cr"],
  ]],
  ["OTHER", N_("OTHER CAREERS"), [
    ["Trading", "Market_Profits", N_("trade profits"), "cr"],
    ["Trading", "Markets_Traded_With", N_("markets traded with"), "n"],
    ["Combat", "Bounties_Claimed", N_("bounties claimed"), "n"],
    ["Combat", "Bounty_Hunting_Profit", N_("bounty hunting"), "cr"],
    ["Passengers", "Passengers_Missions_Delivered", N_("passengers delivered"), "n"],
    ["Search_And_Rescue", "SearchRescue_Traded", N_("rescued and salvaged"), "n"],
    ["Crafting", "Count_Of_Used_Engineers", N_("engineers used"), "n"],
    ["Crafting", "Recipes_Generated", N_("engineering rolls"), "n"],
    ["Material_Trader_Stats", "Trades_Completed", N_("material trades"), "n"],
    ["Smuggling", "Black_Markets_Profits", N_("black market"), "cr"],
    ["Crime", "Total_Fines", N_("fines"), "cr"],
  ]],
];

let root = null, data = null, busy = false;
let days = Number(localStorage.getItem("fis.stat.days") || "30");
// 5.0 (night 18.11.): sub-tabs instead of one long page - current state,
// then the course over time, then rates and times, then what the models
// learnt (its own sub-tab since 18.11., user: more width for every pane).
// Each pane is a list of rows, each row
// a list of columns, each column a list of frames: fixed columns that stack
// their frames, so a short frame no longer stretches to its tall neighbour.
const PANES = [
  ["overview", N_("OVERVIEW"), [[["ranks", "EXPLORATION"], ["EXOBIOLOGY", "WEALTH"], ["CARRIER", "carrierMoney", "MINING", "OTHER"]]]],
  ["trends", N_("HISTORY"), [[["overTime", "surfaceMaps"], ["firstFinds"], ["perSession"]]]],
  ["rates", N_("RATES & TIMES"), [[["bioRates"]], [["timePerSystem"]]]],
  ["learning", N_("LEARNING STATUS"), [[["learning"]]]],
];
let sub = localStorage.getItem("fis.stat.sub") || "overview";

export function mount(r) { root = r; root.classList.add("stat-view"); }

export async function update(ctx, reason) {
  if (!root || busy) return;
  if (reason !== "show" && reason !== "data" && data) return;
  busy = true;
  try { data = await getJSON("/api/statistics" + (days ? "?days=" + days : "")); } catch (e) { data = null; }
  busy = false;
  render();
}

function value(v, kind) {
  if (v === null || v === undefined) return "–";
  if (kind === "cr") return Math.abs(v) >= 1e9 ? fmt(v / 1e9, 2) + " " + t("bn Cr") : Math.abs(v) >= 1e6 ? fmt(v / 1e6, 1) + " M Cr" : fmt(v, 0) + " Cr";
  if (kind === "ly") return fmt(v, 0) + " ly";
  if (kind === "ly1") return fmt(v, 1) + " ly";
  if (kind === "t") return fmt(v, 0) + " t";
  if (kind === "h") return fmt(v / 3600, 0) + " h";
  if (kind === "km") return fmt(v / 1000, 1) + " km";
  return fmt(v, 0);
}

function render() {
  if (!root) return;
  root.replaceChildren();
  if (!data || data.empty) {
    root.append(frame(t("STATISTICS"), "", el("div", { class: "empty" }, t("NO STATISTICS YET"), el("br"),
      el("span", { class: "c-dim", text: t("The game writes them at every login.") }))));
    const lr = data && learning();
    if (lr) root.append(el("div", { class: "stat-wrap" }, el("div"), el("div", { class: "stat-side scroll" }, lr)));
    return;
  }
  const sel = el("select", { class: "lay-pick", onchange: (e) => {
    days = Number(e.target.value); localStorage.setItem("fis.stat.days", String(days)); update(null, "data");
  } }, ...SPANS.map(([v, l]) => el("option", { value: String(v), text: t(l) })));
  sel.value = String(days);
  const since = data.since_ts ? new Date(data.since_ts * 1000).toLocaleDateString() : "";
  if (!PANES.some(([k]) => k === sub)) sub = "overview";
  const tabs = el("div", { class: "kc-tabs st-tabs" }, ...PANES.map(([k, label]) => el("button", { class: sub === k ? "on" : "",
    "aria-pressed": sub === k ? "true" : "false", "data-sub": k, text: t(label),
    onclick: () => { sub = k; localStorage.setItem("fis.stat.sub", k); render(); } })));
  const head = withPopout(frame(t("STATISTICS"), t("as of {d}", { d: new Date(data.ts * 1000).toLocaleString() }), [
    el("div", { class: "gal-row st-headrow" }, el("span", { class: "c-dim", text: t("Growth over") }), sel,
      el("span", { class: "c-green small", text: since ? "+ " + t("since {d}", { d: since }) : "" }), tabs),
    el("div", { class: "c-dim small", text: t("The game's own numbers, written at every login; the journals reach back to {d}.",
      { d: new Date(data.first_ts * 1000).toLocaleDateString() }) }),
  ], { cls: "st-head", appear: false }), "statistics");
  root.append(el("div", { class: "stat-wrap solo" }, el("div", { class: "stat-main" }, head, pane(sub))));
}

const BUILD = { ranks: () => ranks(), overTime: () => overTime(), firstFinds: () => firstFinds(), surfaceMaps: () => surfaceMaps(),
  bioRates: () => bioRates(), perSession: () => perSession(), timePerSystem: () => timePerSystem(), learning: () => learning(),
  carrierMoney: () => carrierMoney() };
for (const c of CARDS) BUILD[c[0]] = () => card(c);

/** One sub-tab: its rows of columns; empty frames and columns drop out. */
function pane(key) {
  const rows = PANES.find(([k]) => k === key)[2].map((cols) => {
    const built = cols.map((col) => col.map((k) => BUILD[k]()).filter(Boolean)).filter((col) => col.length);
    return built.length ? el("div", { class: "st-cols", style: "--n: " + built.length },
      ...built.map((col) => el("div", { class: "st-col" }, ...col))) : null;
  }).filter(Boolean);
  return el("div", { class: "st-pane st-pane-" + key + " scroll" },
    ...(rows.length ? rows : [el("div", { class: "empty c-dim", text: t("Nothing here yet.") })]));
}

// CT2: the carrier's income and costs, Frontier's figures and the journal's
function carrierMoney() {
  const M = data.carrier_money;
  if (!M) return null;
  return frame(t("CARRIER MONEY"), M.frontier ? t("Frontier") : t("journal"), carrierMoneyRows(M, { crew: false }),
    { cls: "st-card", appear: false });
}

// L4: what the FIS has learnt from your own data - and where it is still thin
function learning() {
  const L = data.learning;
  if (!L) return null;
  const rows = [];
  const line = (label, value, thin) => el("div", { class: "st-row" + (thin ? " c-dim" : "") },
    el("span", { text: label }), el("span", { class: "num", text: value }), el("span", { class: "num small " + (thin ? "c-amber" : "c-green"), text: thin ? t("thin") : "✓" }));
  const head = (s) => el("div", { class: "c-cyan small st-learn-h", text: s });
  if (L.models) rows.push(...modelRows(L.models, line, head));
  if (L.finds) rows.push(...findRows(L.finds, line, head));
  if (L.forecast) rows.push(...forecastRows(L.forecast, line, head));
  if (L.reality) rows.push(...realityRows(L.reality, head));
  if (L.rocks.length) {
    rows.push(head(t("Prospected rocks per ring class and hotspot (needs {n})", { n: L.min_rocks })));
    for (const r of L.rocks) rows.push(line(r.cls + (r.hotspot ? " · " + r.hotspot : " · " + t("all")),
      t(r.rings === 1 ? "{n} rocks · 1 ring" : "{n} rocks · {r} rings", { n: r.rocks, r: r.rings }), r.thin));
  }
  if (L.runs.length) {
    rows.push(head(t("Mining runs per ring class and material (needs {n})", { n: L.thin_runs })));
    for (const r of L.runs) rows.push(line(r.cls + " · " + (r.name || r.mat), (r.runs === 1 ? t("1 run") : t("{n} runs", { n: r.runs })) + " · " + fmt(r.t_h, 1) + " t/h", r.thin));
  }
  if (L.rigs.length) {
    rows.push(head(t("Rhino rigs per planet class (needs {n})", { n: L.thin_rigs })));
    for (const r of L.rigs) rows.push(line(r.cls, t("{n} rigs", { n: r.rigs }) + " · " + fmt(r.t_per_rig, 1) + " t/rig", r.thin));
  }
  rows.push(head(t("Bio model: {b} bodies with analysed species, {g} genera", { b: L.bio.bodies, g: L.bio.genera.length })));
  for (const g of L.bio.genera) rows.push(line(g.genus, g.bodies === 1 ? t("1 body") : t("{n} bodies", { n: g.bodies }), g.thin));
  if (!L.rocks.length && !L.runs.length && !L.rigs.length && !L.bio.genera.length)
    rows.push(el("div", { class: "c-dim", text: t("Nothing learnt yet - prospect rocks, mine, collect rigs, analyse organisms.") }));
  const thin = L.thin.rocks + L.thin.runs + L.thin.rigs + L.thin.genera;
  rows.push(el("div", { class: "c-dim small", text: t("Counting and averages from your own journals and the plugin database (all commanders) - no AI. Thin groups lean on broader ones.") }));
  return frame(t("LEARNING STATUS"), thin ? t("{n} still thin", { n: thin }) : "", rows, { cls: "st-card st-learning", appear: false });
}

// SK3: the route, work and fuel models - what each learnt from, since when, and a reset
const MODEL_PARTS = { route: N_("route minutes"), work: N_("scan and sample times"), fuel: N_("fuel model of this ship"),
  value: N_("exploration values") };

async function resetModel(part) {
  if (!window.confirm(t("Reset the {m}? What it learnt is forgotten; only journals from now on count - here and in the plugin at its next start.",
    { m: t(MODEL_PARTS[part]) }))) return;
  try { await postJSON("/api/learning/reset", { part }); } catch (e) { window.alert(t("Reset failed: {e}", { e: e.message })); return; }
  update(null, "data");
  setTimeout(() => update(null, "data"), 2500);      // the route and work models are measured again in the background
}

// FX3: the chance of a find predicted at each first arrival, against what the scans showed (V0)
function findRows(F, line, head) {
  const pc = (v) => v === null || v === undefined ? "–" : fmt(100 * v, 0) + " %";
  const base = (k) => F.base && F.base[k] ? t("{h} of {n}", { h: F.base[k].hits, n: F.base[k].n }) : "–";
  const rows = [head(t("Finds: predicted at arrival vs. scans (learnt from {n} systems)", { n: F.learnt }))];
  rows.push(line(t("Systems with an undiscovered body"), t("procgen {pg} · named {nm}", { pg: base("pg"), nm: base("named") }), F.learnt < 10));
  for (const b of F.bands) {
    if (!b.n) continue;
    const label = t("predicted {a}–{b}", { a: fmt(100 * b.from, 0), b: b.to === null ? "100" : fmt(100 * b.to, 0) }) + " %";
    rows.push(line(label, t("~{p} predicted · {r} found ({lo}–{hi} %) · n {n}",
      { p: pc(b.predicted), r: pc(b.rate), lo: fmt(b.low * 100, 0), hi: fmt(b.high * 100, 0), n: b.n }), b.thin));
  }
  rows.push(el("div", { class: "c-dim small", text: t("{l} predictions kept, {w} wait for a completed FSS", { l: F.logged, w: F.waiting }) }));
  return rows;
}

// V0: every learning model against your own journals - one error value each
const REALITY = { kepler: N_("Kepler positions"), fuel: N_("Fuel per jump"), route: N_("Time per system vs. route estimate"),
  work: N_("Surface scan / bio sample"), value: N_("Exploration value vs. sales"), finds: N_("Chance of a find vs. scans"),
  bio: N_("Bio prediction (genera in top 3)") };

function realityRows(R, head) {
  const rows = [head(t("Reality check: each model against what happened"))];
  for (const r of R) {
    const mark = r.good === true ? "✓" : r.good === false ? "✗" : t("thin");
    rows.push(el("div", { class: "st-row" + (r.value ? "" : " c-dim") },
      el("span", { text: t(REALITY[r.key] || r.label) }),
      el("span", { class: "num", text: (r.value || t("no data yet")) + (r.n ? " · n " + fmt(r.n, 0) : "") }),
      el("span", { class: "num small " + (r.good === true ? "c-green" : r.good === false ? "c-amber" : "c-dim"), text: mark })));
  }
  return rows;
}

// B-24: what is still ahead, from your own data - each with "~", range and n
function forecastRows(F, line, head) {
  const rows = [head(t("Forecasts (from your own data)"))];
  const S = F.sphere, J = F.jumps;
  const hrs = (v) => fmt(v, v < 10 ? 1 : 0);
  if (S && S.hours) rows.push(line(t("Rest of the sphere"), t("{o} systems · ~{h} h ({lo}–{hi}) · learned from {n}",
    { o: S.open, h: hrs(S.hours.mid), lo: hrs(S.hours.lo), hi: hrs(S.hours.hi), n: S.hours.n }), S.thin));
  if (S && S.value) rows.push(line(t("Value still to gather"), t("~{v} M Cr ({lo}–{hi}) · ~{h} M Cr/h · learned from {n} sessions",
    { v: fmt(S.value.mid / 1e6, 0), lo: fmt(S.value.lo / 1e6, 0), hi: fmt(S.value.hi / 1e6, 0), h: fmt(S.value_h / 1e6, 2), n: S.value.n }), S.value.n < 3));
  if (S && S.finds) rows.push(line(t("Finds still to expect"), t("~{f} ({lo}–{hi}) · learned from {n} first visits",
    { f: fmt(S.finds.mid, 0), lo: fmt(S.finds.lo, 0), hi: fmt(S.finds.hi, 0), n: S.finds.n }), S.finds.n < 10));
  if (J) rows.push(line(t("Jumps until the tank is empty"), t("~{m} ({lo}–{hi}) at {d} ly · learned from {n} jumps",
    { m: J.mid, lo: J.lo, hi: J.hi, d: fmt(J.ly, 1), n: J.n }), J.thin));
  if (rows.length === 1) rows.push(el("div", { class: "c-dim small", text: t("No active sphere and no fuel data yet.") }));
  return rows;
}

function modelRows(M, line, head) {
  const rows = [head(t("Route and fuel models (learnt from your journals)"))];
  const reset = (part, since) => el("div", { class: "c-dim small st-row st-reset" },
    el("span", { text: since ? t("reset {d}", { d: new Date(since * 1000).toLocaleString() }) : t("never reset") }), el("span"),
    el("button", { class: "small", text: t("reset"), title: t("Forget what this model learnt"), onclick: () => resetModel(part) }));
  const r = M.route;
  rows.push(line(t("Supercruise per leg"), r.calibrated
    ? t("~{e} s + {k} × √LS · learned from {n} legs", { e: fmt(r.entry_s, 0), k: fmt(r.k, 1), n: r.n })
    : t("default · {n} legs measured", { n: r.measured }), !r.calibrated), reset("route", r.since));
  const w = M.work;
  rows.push(line(t("Surface scan / bio sample"), t("~{d} s · ~{b} s · learned from {n} and {m}",
    { d: fmt(w.dss_s, 0), b: fmt(w.bio_s, 0), n: w.dss_n, m: w.bio_n }), w.dss_n < 3 || w.bio_n < 3), reset("work", w.since));
  const f = M.fuel;
  if (f) rows.push(line(t("Fuel") + " · " + (f.ship || "?"), f.source === "fit"
    ? t("~{x}^{b}, ±{s} % · learned from {n} jumps", { x: f.mass ? t("(distance × mass)") : t("distance"), b: fmt(f.power, 2), s: fmt(f.spread_pct, 1), n: f.n })
    : t("~distance^{b} from the FSD · {n} of 4 jumps", { b: fmt(f.power, 2), n: f.n }), f.source !== "fit"), reset("fuel", null));
  const v = M.value;      // B6
  if (v) rows.push(line(t("Exploration values"), v.factor !== null && v.factor !== undefined
    ? t("~{f} × formula ({lo}–{hi}) · learned from {n} sales", { f: fmt(v.factor, 2), lo: fmt(v.lo, 2), hi: fmt(v.hi, 2), n: v.n })
    : t("formula only · {n} of 3 sales over 1 M Cr", { n: v.n }), v.factor === null || v.factor === undefined), reset("value", v.since));
  return rows;
}

function ranks() {
  const rows = data.ranks.map(r => {
    const pct = r.progress === null || r.progress === undefined ? null : r.progress;
    const top = r.rank >= r.max;
    return el("div", { class: "st-rank" },
      el("span", { class: "c-dim", text: t(RANK_LABEL[r.key] || r.key) }),
      el("span", { class: top ? "c-amber" : "c-cyan", text: r.name + (top ? " ★" : "") }),
      meter(top ? 100 : pct || 0),
      el("span", { class: "num", text: top ? "" : pct === null ? "–" : pct + " %" }));
  });
  const rep = Object.entries(data.reputation || {});
  if (rep.length) rows.push(el("div", { class: "c-dim small", text: t("Reputation") + ": "
    + rep.map(([k, v]) => t(REP_LABEL[k] || k) + " " + fmt(v, 0) + " %").join(" · ") }));
  return frame(t("RANKS"), "", rows, { cls: "st-ranks", appear: false });
}

// ---------------------------------------------------------------- ST1
// one value per day over the chosen period: a single line each (the label
// names it), hover a point for the day and the value
const SERIES = [["Exploration.Systems_Visited", N_("systems visited"), "n"], ["Exploration.Exploration_Profits", N_("exploration data sold"), "cr"],
  ["Exploration.Planets_Scanned_To_Level_3", N_("bodies scanned"), "n"], ["Exobiology.Organic_Data_Profits", N_("exobiology earned"), "cr"],
  ["Mining.Quantity_Mined", N_("tonnes mined"), "t"], ["Bank_Account.Current_Wealth", N_("wealth"), "cr"]];
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function spark(pts, kind) {
  const W = 220, H = 44, P = 6;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (x) => P + (x1 > x0 ? (x - x0) / (x1 - x0) : 0.5) * (W - 2 * P);
  const Y = (y) => H - P - (y1 > y0 ? (y - y0) / (y1 - y0) : 0.5) * (H - 2 * P);
  const line = pts.map(p => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ");
  const dots = pts.map(p => '<circle class="sp-hit" cx="' + X(p[0]).toFixed(1) + '" cy="' + Y(p[1]).toFixed(1) + '" r="7"><title>'
    + esc(new Date(p[0] * 1000).toLocaleDateString() + ": " + value(p[1], kind)) + "</title></circle>").join("");
  const last = pts[pts.length - 1];
  const box = el("span", { class: "st-spark" });
  box.innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(t("trend")) + '"><polyline points="' + line
    + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    + '<circle cx="' + X(last[0]).toFixed(1) + '" cy="' + Y(last[1]).toFixed(1) + '" r="4" fill="currentColor"/>' + dots + "</svg>";
  return box;
}

function overTime() {
  const S = data.series || {};
  const rows = SERIES.filter(([k]) => S[k]).map(([k, label, kind]) => {
    const pts = S[k];
    return el("div", { class: "st-trend" }, el("span", { class: "c-dim", text: t(label) }), spark(pts, kind),
      el("span", { class: "num c-green small", text: (pts[pts.length - 1][1] - pts[0][1] >= 0 ? "+" : "") + value(pts[pts.length - 1][1] - pts[0][1], kind) }));
  });
  if (!rows.length) return null;
  rows.push(el("div", { class: "c-dim small", text: t("The game's numbers at the last login of each day; hover a point for the day.") }));
  return frame(t("OVER TIME"), "", rows, { cls: "st-card", appear: false });
}

// first discoveries per month: bodies you scanned first, as a share of all you scanned
function firstFinds() {
  const F = data.first_discoveries || [];
  if (!F.length) return null;
  const max = Math.max(1, ...F.map(f => f.first));
  const rows = F.map(f => el("div", { class: "st-row st-month", title: t("{f} of {n} bodies you scanned were undiscovered", { f: f.first, n: f.scanned }) },
    el("span", { class: "c-dim", text: f.month }),
    meter(f.first, max),
    el("span", { class: "num", text: fmt(f.first, 0) + " · " + fmt(f.pct, 1) + " %" })));
  rows.push(el("div", { class: "c-dim small", text: t("Your own scans (no nav beacon), each body once; only the active commander. Yours for good once sold.") }));
  return frame(t("FIRST DISCOVERIES PER MONTH"), "", rows, { cls: "st-card", appear: false });
}

function surfaceMaps() {
  const D = data.dss;
  if (!D) return null;
  const mm = (s) => s === null || s === undefined ? "–" : Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0") + " min";
  const rows = [
    el("div", { class: "st-row" }, el("span", { class: "c-dim", text: t("surface maps") }), el("span", { class: "num", text: fmt(D.maps, 0) })),
    el("div", { class: "st-row" }, el("span", { class: "c-dim", text: t("efficient") }),
      el("span", { class: "num", text: D.efficient_pct === null ? "–" : fmt(D.efficient_pct, 1) + " % (" + fmt(D.efficient, 0) + "/" + fmt(D.rated, 0) + ")" })),
    el("div", { class: "st-row" }, el("span", { class: "c-dim", text: t("probes per map (median)") }), el("span", { class: "num", text: D.probes_median === null ? "–" : fmt(D.probes_median, 0) })),
    el("div", { class: "st-row" }, el("span", { class: "c-dim", text: t("time per map") }),
      el("span", { class: "num", text: "~" + mm(D.gap_median_s) + " (" + mm(D.gap_q1_s) + " – " + mm(D.gap_q3_s) + ", n " + fmt(D.gap_n, 0) + ")" })),
    el("div", { class: "c-dim small", text: t("Time per map: between two maps in one system less than 15 minutes apart - flying there and mapping; median with the middle half.") }),
  ];
  return frame(t("SURFACE MAPS"), "", rows, { cls: "st-card", appear: false });
}

// BQ1: how often a landable planet carried life, by atmosphere, planet class and
// main star - with the 95 % interval - and the bio model's own check (V0)
function bioRates() {
  const B = data.bio_rates;
  if (!B || !B.planets) return null;
  const rows = [];
  const sect = (title, list) => {
    if (!list.length) return;
    const box = el("div", { class: "st-rate-sect" }, el("div", { class: "c-cyan small st-learn-h", text: title }));
    groups.append(box);
    for (const g of list) box.append(el("div", { class: "st-row st-month st-rate", title: t("{b} of {n} landable planets with biological signals; 95 % interval {lo}–{hi} %", { b: g.bio, n: g.n, lo: fmt(g.lo, 1), hi: fmt(g.hi, 1) }) },
      el("span", { class: "c-dim", text: g.key === "none" ? t("no atmosphere") : g.key }),
      meter(g.pct),
      el("span", { class: "num", text: fmt(g.pct, 0) + " % · n " + fmt(g.n, 0) })));
  };
  const groups = el("div", { class: "st-rate-groups" });
  rows.push(groups);
  sect(t("by atmosphere"), B.atmo);
  sect(t("by planet class"), B.pclass);
  sect(t("by the system's main star"), B.star);
  if (B.v0 && B.v0.bodies) rows.push(el("div", { class: "small", text: t("Bio model check (leave one out, {n} sampled bodies): real genera among the top 3 predicted {r} %, the first one right {f} %",
    { n: B.v0.bodies, r: fmt(100 * B.v0.recall_top3, 0), f: fmt(100 * B.v0.top1_right, 0) }) }));
  rows.push(el("div", { class: "c-dim small", text: t("Every landable planet scanned on this PC; groups from {m} planets on. A rate, not a promise: hover for the interval.", { m: B.min_n }) }));
  if (B.from_archive) rows.push(el("div", { class: "c-dim small", text: t("{n} of them from the EDDiscovery archive (scans since Odyssey the plugin database does not have).", { n: fmt(B.from_archive, 0) }) }));
  return frame(t("BIO RATES"), t("{b} of {n} with life", { b: fmt(B.with_bio, 0), n: fmt(B.planets, 0) }), rows, { cls: "st-card", appear: false });
}

// RT1: systems and gathered value per hour, per game session
function perSession() {
  const P = data.sessions;
  if (!P || !P.sessions.length) return null;
  const rows = [el("div", { class: "st-row" }, el("span", { class: "c-dim", text: t("median of {n} sessions of 30 min or more", { n: P.n }) }),
    el("span", { class: "num", text: (P.jumps_h === null ? "–" : fmt(P.jumps_h, 1)) + " " + t("systems/h") }),
    el("span", { class: "num c-green", text: P.valued && P.value_h !== null ? "~" + value(P.value_h, "cr") + "/h" : "" }))];
  for (const s of P.sessions) rows.push(el("div", { class: "st-row",
    title: t("{m} min · {j} jumps · {b} bodies · exploration ~{e} · bio {o}", { m: s.minutes, j: s.jumps, b: s.bodies, e: value(s.explo, "cr"), o: value(s.bio, "cr") }) },
    el("span", { class: "c-dim", text: new Date(s.start * 1000).toLocaleDateString() + " · " + s.minutes + " min" }),
    el("span", { class: "num", text: fmt(s.jumps_h, 1) + " " + t("systems/h") }),
    el("span", { class: "num small", text: !P.valued ? "" : s.value_h === null ? "–" : "~" + value(s.value_h, "cr") + "/h" })));
  rows.push(el("div", { class: "c-dim small", text: t("Value gathered, not sold: the formula's estimate of every body you scanned or mapped, first discoveries or not, plus your own prices of the species analysed - hence ~. The value median takes only sessions with scans in the journals ({n} of them; the EDD archive keeps hardly any scans before 2023). A pause of 30 min or a login starts a new session.", { n: P.n_value === undefined ? P.n : P.n_value }) }));
  return frame(t("PER SESSION"), "", rows, { cls: "st-card", appear: false });
}

// own-4 (17.11.): how long each system took and on what, against the route's
// first estimate after the FSS (kept by the plugin since 5.0)
const hm = (min) => min === null || min === undefined ? "–" : Math.floor(min / 60) + ":" + String(Math.round(min % 60)).padStart(2, "0");

function timePerSystem() {
  const T = data.systime;
  if (!T || !T.systems.length) return null;
  const rows = [el("div", { class: "st-row" },
    el("span", { class: "c-dim", text: t("median per system") }),
    el("span", { class: "num", text: hm(T.median_min) + " h" }),
    el("span", { class: "num " + (T.ratio === null ? "c-dim" : "c-green"), text: T.ratio === null ? "" : "×" + fmt(T.ratio, 2) })),
    el("div", { class: "c-dim small", text: T.ratio === null ? t("No estimate kept yet - from 5.0 on the plugin keeps the route's first estimate once your FSS is complete.")
      : t("You take {r} × the route's estimate (median of {n} systems).", { r: fmt(T.ratio, 2), n: T.ratio_n }) }),
    el("div", { class: "st-row st-systime c-cyan small" }, el("span", { text: t("system") }), el("span", { class: "num", text: t("time") }),
      el("span", { class: "num", text: t("estimate") }), el("span", { class: "num", text: "×" }))];
  for (const s of T.systems.slice(0, 15)) {
    const work = [s.maps ? t("{n} maps", { n: s.maps }) : "", s.bio ? t("{n} species", { n: s.bio }) : "",
      s.landings ? t("{n} landings", { n: s.landings }) : ""].filter(Boolean).join(" · ") || t("scans only");
    rows.push(el("div", { class: "st-row st-systime", title: t("{v} visits · {b} bodies scanned · FSS {h}×", { v: s.visits, b: s.scans, h: s.honk }) },
      el("span", {}, el("div", { text: new Date(s.first * 1000).toLocaleDateString() + " · " + s.name }), el("div", { class: "c-dim small", text: work })),
      el("span", { class: "num", text: hm(s.minutes) }),
      el("span", { class: "num c-dim", text: s.estimate === null ? "–" : "~" + hm(s.estimate) }),
      el("span", { class: "num " + (s.ratio === null ? "c-dim" : s.ratio > 1.5 ? "c-amber" : "c-green"), text: s.ratio === null ? "" : fmt(s.ratio, 1) })));
  }
  rows.push(el("div", { class: "c-dim small", text: t("Time in a system from the arrival to the next jump; a pause of 30 min does not count. Systems you only passed through are left out. Active commander.") }));
  return frame(t("TIME PER SYSTEM"), t("{n} systems · {h} h", { n: T.n, h: fmt(T.hours, 0) }), rows, { cls: "st-card", appear: false });
}

function card([key, title, fields]) {
  const rows = [];
  for (const [sec, f, label, kind] of fields) {
    const src = sec === "derived" ? data.derived || {} : (data.sections[sec] || {});
    if (src[f] === undefined) continue;
    const d = sec === "derived" ? null : ((data.delta[sec] || {})[f]);
    // the first figure of a card is its lead (a theme may show it large)
    rows.push(el("div", { class: rows.length ? "st-row" : "st-row st-lead" },
      el("span", { class: "c-dim", text: t(label) }),
      el("span", { class: "num", text: value(src[f], kind) }),
      el("span", { class: "num c-green small", text: d ? (d > 0 ? "+" : "") + value(d, kind) : "" })));
  }
  if (!rows.length) return null;
  return frame(t(title), "", rows, { cls: "st-card st-" + key.toLowerCase(), appear: false });
}
