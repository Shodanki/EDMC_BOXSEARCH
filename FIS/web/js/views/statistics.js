// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// STATISTICS – the game's own record of the commander (the Statistics event
// written at every login), research first: ranks with progress, exploration,
// exobiology, mining, the carrier, wealth - and the growth over a chosen
// period (the Statistics event from back then against the latest one).

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";

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
  const head = withPopout(frame(t("STATISTICS"), t("as of {d}", { d: new Date(data.ts * 1000).toLocaleString() }), [
    el("div", { class: "gal-row" }, el("span", { class: "c-dim", text: t("Growth over") }), sel,
      el("span", { class: "c-green small", text: since ? "+ " + t("since {d}", { d: since }) : "" })),
    el("div", { class: "c-dim small", text: t("The game's own numbers, written at every login; the journals reach back to {d}.",
      { d: new Date(data.first_ts * 1000).toLocaleDateString() }) }),
  ], { appear: false }), "statistics");
  // the learning status in a column of its own on the right - no scrolling down to it (11.11.)
  const lr = learning();
  root.append(el("div", { class: "stat-wrap" + (lr ? "" : " solo") },
    el("div", { class: "stat-grid scroll" }, head, ranks(), ...CARDS.map(card)),
    lr ? el("div", { class: "stat-side scroll" }, lr) : null));
}

// L4: what the FIS has learnt from your own data - and where it is still thin
function learning() {
  const L = data.learning;
  if (!L) return null;
  const rows = [];
  const line = (label, value, thin) => el("div", { class: "st-row" + (thin ? " c-dim" : "") },
    el("span", { text: label }), el("span", { class: "num", text: value }), el("span", { class: "num small " + (thin ? "c-amber" : "c-green"), text: thin ? t("thin") : "✓" }));
  const head = (s) => el("div", { class: "c-cyan small st-learn-h", text: s });
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

function ranks() {
  const rows = data.ranks.map(r => {
    const pct = r.progress === null || r.progress === undefined ? null : r.progress;
    const top = r.rank >= r.max;
    return el("div", { class: "st-rank" },
      el("span", { class: "c-dim", text: t(RANK_LABEL[r.key] || r.key) }),
      el("span", { class: top ? "c-amber" : "c-cyan", text: r.name + (top ? " ★" : "") }),
      el("span", { class: "lbar" }, el("i", { style: { width: (top ? 100 : pct || 0) + "%" } })),
      el("span", { class: "num", text: top ? "" : pct === null ? "–" : pct + " %" }));
  });
  const rep = Object.entries(data.reputation || {});
  if (rep.length) rows.push(el("div", { class: "c-dim small", text: t("Reputation") + ": "
    + rep.map(([k, v]) => t(REP_LABEL[k] || k) + " " + fmt(v, 0) + " %").join(" · ") }));
  return frame(t("RANKS"), "", rows, { cls: "st-ranks", appear: false });
}

function card([key, title, fields]) {
  const rows = [];
  for (const [sec, f, label, kind] of fields) {
    const src = sec === "derived" ? data.derived || {} : (data.sections[sec] || {});
    if (src[f] === undefined) continue;
    const d = sec === "derived" ? null : ((data.delta[sec] || {})[f]);
    rows.push(el("div", { class: "st-row" },
      el("span", { class: "c-dim", text: t(label) }),
      el("span", { class: "num", text: value(src[f], kind) }),
      el("span", { class: "num c-green small", text: d ? (d > 0 ? "+" : "") + value(d, kind) : "" })));
  }
  if (!rows.length) return null;
  return frame(t(title), "", rows, { cls: "st-card st-" + key.toLowerCase(), appear: false });
}
