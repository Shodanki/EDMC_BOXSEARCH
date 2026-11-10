// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// CARRIER – the fleet carrier as a navy ship's sheet, plus the air wing for
// the CAG: which ships are on board, what each is fitted for, ready where.
//
// Sections in reading order: identity · position and orders · tritium and
// range · hold · finances · services · air wing. Numbers come from the
// journal (CarrierStats, jumps, transfers); the weekly cost is an estimate
// from the balance over time and says so.

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";

const ROLES = [["combat", N_("Combat")], ["mining", N_("Mining")], ["transport", N_("Transport")],
  ["exploration", N_("Exploration")], ["passengers", N_("Passengers")], ["sar", N_("SAR")]];
const ROLE_HELP = { combat: N_("Combat: weapons by mount size, shield size and class, shield boosters, hull reinforcement, armour"), mining: N_("Mining: mining lasers and tools, refinery, prospector and collector limpet controllers, pulse wave scanner; ground mining: at least 2 when the SRV Rhino was launched from this ship"), transport: N_("Transport: cargo capacity - 5 dots from 500 t"), exploration: N_("Exploration: jump range - 5 dots from 60 ly; without a fuel scoop at most 1, without a surface scanner at most 2, without a vehicle hangar (exobiology) at most 4, a Nomad hangar adds one"), passengers: N_("Passengers: passenger cabins"), sar: N_("Search and rescue: repair and fuel transfer limpets, fuel to give, fuel scoop, decontamination and collector limpets") };
const SPACE = [["crew", N_("crew"), "c1"], ["cargo", N_("cargo"), "c2"], ["reserved", N_("reserved"), "c3"],
  ["ships", N_("ship packs"), "c4"], ["modules", N_("module packs"), "c5"]];
const SERVICE = { BlackMarket: N_("Secure warehouse"), Captain: N_("Captain"), Refuel: N_("Refuel"),
  Repair: N_("Repair"), Rearm: N_("Rearm"), Commodities: N_("Commodities"), VoucherRedemption: N_("Redemption office"),
  Exploration: N_("Universal Cartographics"), Shipyard: N_("Shipyard"), Outfitting: N_("Outfitting"),
  CarrierFuel: N_("Tritium depot"), VistaGenomics: N_("Vista Genomics"), PioneerSupplies: N_("Pioneer Supplies"),
  Bartender: N_("Bar") };

const ACCESS = { all: N_("everyone"), friends: N_("friends"), squadron: N_("squadron"),
  squadronfriends: N_("squadron and friends"), none: N_("nobody") };

const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* private window */ } return null; };
let root = null, data = null, roleFilter = store("fis.cag.role") || "";
// E4: ship list sortable by every column, with a text filter and "on board only"
let sortKey = store("fis.cag.sort") || "", sortDir = store("fis.cag.dir") === "asc" ? 1 : -1;
let shipQuery = "", onBoardOnly = store("fis.cag.here") === "1";

export function mount(r) { root = r; root.classList.add("carrier-view"); }

export async function update(ctx, reason) {
  if (!root) return;
  if (reason !== "show" && reason !== "data" && data) return;
  try { data = await getJSON("/api/carrier"); } catch (e) { data = null; }
  render();
}

function day(ts) {
  if (!ts) return "–";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "2-digit", year: "numeric" });
}
function age(s) {
  if (s === null || s === undefined) return "?";
  return s < 3600 ? t("{n} min ago", { n: Math.max(1, Math.round(s / 60)) }) : s < 172800 ? t("{n} h ago", { n: Math.round(s / 3600) })
    : t("{n} days ago", { n: Math.round(s / 86400) });
}
function cr(v) { return v === null || v === undefined ? "–" : fmt(v / 1e6, 1) + " M Cr"; }
function line(k, ...v) { return el("div", { class: "ns-row" }, el("div", { class: "ns-k", text: k }), el("div", { class: "ns-v" }, ...v)); }

// M7: docked at someone else's carrier - what it buys (how you can help) and sells
function visiting() {
  const v = data.visiting;
  const rows = [];
  if (!v.buys.length && !v.sells.length) rows.push(el("div", { class: "c-dim", text: t("This carrier trades nothing right now.") }));
  if (v.buys.length) {
    rows.push(el("div", { class: "sr-h", text: t("IT BUYS") }));
    for (const b of v.buys.slice(0, 12)) rows.push(el("div", { class: "cg" + (b.carry ? " c-green" : b.key === "tritium" ? " c-amber" : "") },
      el("span", { text: b.name + (b.carry ? "  · " + t("you carry {n} t", { n: b.carry }) : "") }),
      el("span", { class: "num", text: fmt(b.demand, 0) + " t · " + fmt(b.price, 0) + " Cr" })));
  }
  if (v.sells.length) {
    rows.push(el("div", { class: "sr-h", text: t("IT SELLS") }));
    for (const s of v.sells.slice(0, 8)) rows.push(el("div", { class: "cg" },
      el("span", { text: s.name }), el("span", { class: "num", text: fmt(s.stock, 0) + " t · " + fmt(s.price, 0) + " Cr" })));
  }
  rows.push(el("div", { class: "c-dim small", text: t("From the market you opened at {d} - open it again for fresh figures.", { d: String(v.market_ts || "").slice(11, 16) }) }));
  return frame(t("DOCKED AT A CARRIER"), (v.callsign || "") + (v.system ? " · " + v.system : ""), rows, { appear: false });
}

function render() {
  if (!root) return;
  root.replaceChildren();
  if (data && data.visiting) root.append(visiting());
  if (!data || data.empty) {
    root.append(frame(t("CARRIER"), "", el("div", { class: "empty" }, t("NO CARRIER DATA"), el("br"),
      el("span", { class: "c-dim", text: t("No carrier of your own known yet - your ships are listed below. If you own one, open the carrier management once.") }))));
    if (data && data.fleet && data.fleet.length) root.append(airWing());
    return;
  }
  root.append(el("div", { class: "ns-grid" },
    el("div", { class: "ns-col" }, ident(), position(), tritium()),
    el("div", { class: "ns-col" }, hold(), finance(), services())), airWing());
}

function ident() {
  const i = data.ident;
  const fr = frame(t("CARRIER"), i.callsign || "", [
    el("div", { class: "ns-name" }, el("span", { class: "c-cyan", text: i.name || "?" }), el("span", { class: "c-dim", text: "  " + (i.callsign || "") })),
    line(t("Docking"), (ACCESS[i.access] ? t(ACCESS[i.access]) : (i.access || "–"))
      + (i.notorious ? " · " + t("notorious allowed") : "")),
    i.decommission ? line(t("STATUS"), el("span", { class: "c-red", text: t("DECOMMISSIONING PENDING") })) : null,
    el("div", { class: "c-dim small", text: t("as of {d}", { d: day(i.stats_ts) }) }),
  ], { cls: "ns-ident", appear: false });
  return withPopout(fr, "carrier");
}

function position() {
  const p = data.position;
  const rows = [line(t("Position"), el("span", { class: "c-cyan", text: p.system || "–" }), el("span", { class: "c-dim", text: "  " + t("since {d}", { d: day(p.ts) }) }))];
  if (p.pending) rows.push(line(t("Orders"), el("span", { class: "c-amber", text: "⟫ " + p.pending.to + (p.pending.ly ? " · " + fmt(p.pending.ly, 1) + " ly" : "")
    + (p.pending.tritium ? " · ~" + p.pending.tritium + " t" : "") + (p.pending.departure ? " · " + new Date(p.pending.departure).toLocaleString() : "") })));
  if (p.jumps.length) {
    rows.push(el("div", { class: "ns-sub", text: t("LAST JUMPS") }));
    rows.push(el("table", { class: "ns-tab" },
      el("tr", {}, ...["", t("to"), "ly", t("used"), t("calc.")].map(h => el("th", { text: h }))),
      ...p.jumps.slice(0, 6).map(j => el("tr", {},
        el("td", { class: "c-dim", text: day(j.ts) }), el("td", { text: j.to || "?" }),
        el("td", { class: "num", text: j.ly !== null ? fmt(j.ly, 1) : "–" }),
        el("td", { class: "num", text: j.used !== null ? j.used + " t" : "–" }),
        el("td", { class: "num c-dim", text: j.predicted !== null ? j.predicted + " t" : "–" })))));
  }
  return frame(t("POSITION & ORDERS"), "", rows, { appear: false });
}

function tritium() {
  const tr = data.tritium, r = tr.range;
  const pctTank = Math.round(100 * (tr.tank || 0) / tr.tank_max);
  return frame(t("TRITIUM & RANGE"), pctTank + " %", [
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Tank") }),
      el("span", { class: "lbar " + (pctTank < 25 ? "warn" : "") }, el("i", { style: { width: pctTank + "%" } })),
      el("span", { text: fmt(tr.tank, 0) + " / " + fmt(tr.tank_max, 0) + " t" })),
    line(t("Range"), el("span", { class: "big c-green", text: fmt(r.ly, 0) + " ly" }),
      el("span", { class: "c-dim", text: "  " + t("{n} full jumps of 500 ly", { n: r.jumps }) })),
    line(t("Per 500 ly"), fmt(tr.per_max_jump, 0) + " t " + t("at {l} t load", { l: fmt(tr.load, 0) })),
    line(t("To a full tank"), fmt(tr.to_full, 0) + " t"),
    tr.ship !== undefined ? line(t("In your ship"), fmt(tr.ship, 0) + " t",
      tr.with_ship ? el("span", { class: "c-dim", text: "  → " + t("tank filled: {ly} ly", { ly: fmt(tr.with_ship.ly, 0) }) }) : null) : null,
    tr.mined ? line(tr.mined.active ? t("Mining now") : t("Last mining"),
      el("span", { class: "c-green", text: "+" + fmt(tr.mined.t, 0) + " t" }),
      el("span", { class: "c-dim", text: "  ≈ " + t("{j} jumps · {ly} ly", { j: fmt(tr.mined.jumps, 1), ly: fmt(tr.mined.ly, 0) }) })) : null,
    tr.trip ? line(t("To your route's end"),
      el("span", { text: t("{to}: {ly} ly · {n} jumps · {need} t", { to: tr.trip.to || "?", ly: fmt(tr.trip.ly, 0), n: tr.trip.jumps, need: fmt(tr.trip.need, 0) }) }),
      el("span", { class: tr.trip.enough ? "c-green" : "c-amber", text: "  " + (tr.trip.enough ? t("enough") : t("{s} t short", { s: fmt(tr.trip.short, 0) })) })) : null,
    tr.hold ? line(t("In the carrier's hold"), fmt(tr.hold.t, 0) + " t",
      tr.with_hold ? el("span", { class: "c-green", text: "  → " + t("with it: {ly} ly · {n} jumps", { ly: fmt(tr.with_hold.ly, 0), n: tr.with_hold.jumps }) }) : null,
      el("span", { class: "c-dim small", text: "  " + t("Frontier data, {a}", { a: age(tr.hold.age_s) }) }))
      : el("div", { class: "c-dim small", text: t("Tritium in the carrier's hold comes with EDMC's Frontier data (Companion API) - none yet.") }),
    el("div", { class: "c-dim small", text: t("Formula fitted on your own jumps (±1 t): {f}", { f: tr.formula }) }),
  ], { appear: false });
}

function hold() {
  const s = data.space, tot = s.total || 25000;
  const stack = el("div", { class: "hold-stack" }, ...SPACE.map(([k, , c]) =>
    el("i", { class: c, style: { width: (100 * (s[k] || 0) / tot).toFixed(2) + "%" }, title: k + ": " + fmt(s[k] || 0, 0) + " t" })));
  return frame(t("HOLD"), t("{n} t free", { n: fmt(s.free, 0) }), [stack,
    el("div", { class: "hold-legend" }, ...SPACE.map(([k, label, c]) => el("span", { class: "hl " + c },
      el("b", { text: "■ " }), t(label) + " " + fmt(s[k] || 0, 0))),
      el("span", { class: "hl", text: "□ " + t("free") + " " + fmt(s.free, 0) })), goods()], { appear: false });
}

// the hold per good - only Frontier's data (Companion API) has it
function goods() {
  const c = data.capi;
  if (!c) return el("div", { class: "c-dim small", text: t("Goods in the hold come with EDMC's Frontier data (Companion API) - none yet.") });
  return el("div", { class: "fc-goods" },
    el("div", { class: "c-dim small", text: t("{n} t of goods · Frontier data, {a}", { n: fmt(c.hold_total, 0), a: age(c.age_s) }) }),
    el("div", { class: "cargo scroll" }, ...c.hold.slice(0, 40).map(g => el("div", { class: "cg" + (g.stolen ? " hot" : "") },
      el("span", { text: g.name + (g.stolen ? " ⚠" : "") + (g.mission ? " ◆" : "") }),
      el("span", { class: "num", text: fmt(g.qty, 0) + " t" })))));
}

function finance() {
  const f = data.finance;
  const rows = [
    line(t("Balance"), cr(f.balance)),
    line(t("Reserve"), cr(f.reserve) + (f.reserve_pct !== null ? " · " + f.reserve_pct + " %" : "")),
    line(t("Available"), el("span", { class: "c-green", text: cr(f.available) })),
  ];
  if (f.per_week) {
    const until = f.weeks_left ? new Date(Date.now() + f.weeks_left * 7 * 86400000) : null;
    const exact = f.per_week_source === "frontier";
    rows.push(line(t("Cost per week"), el("span", { class: "c-amber", text: (exact ? "" : "~") + cr(f.per_week) }),
      el("span", { class: "c-dim", text: "  " + (exact
        ? t("Frontier: core {c} + services {s}", { c: cr(f.upkeep.core), s: cr(f.upkeep.services) })
        : t("estimate over {d} days", { d: fmt(f.basis_days, 0) })) })));
    if (until) rows.push(line(t("Lasts until"), el("span", { class: f.weeks_left < 8 ? "c-red" : f.weeks_left < 26 ? "c-amber" : "c-green",
      text: day(until.getTime() / 1000) }), el("span", { class: "c-dim", text: "  (" + t("{w} weeks", { w: fmt(f.weeks_left, 0) }) + ")" })));
  } else {
    rows.push(line(t("Cost per week"), el("span", { class: "c-dim", text: t("not measurable – income at the carrier covers the costs") })));
  }
  if (f.per_week_source !== "frontier")
    rows.push(el("div", { class: "c-dim small", text: t("Estimate: balance change with your own transfers taken out; market income at the carrier cannot be separated.") }));
  return frame(t("FINANCES"), "", rows, { appear: false });
}

function services() {
  return frame(t("SERVICES"), "", el("div", { class: "svc" }, ...data.services.map(s => el("span", {
    class: "chip " + (s.active ? (s.enabled === false ? "warn" : "mapped") : "off"),
    title: s.crew || "", text: SERVICE[s.role] ? t(SERVICE[s.role]) : s.role }))), { appear: false });
}

// ------------------------------------------------------------ air wing (CAG)
function dots(n) { return "●".repeat(n) + "○".repeat(5 - n); }

function airWing() {
  const ships = data.fleet || [];
  const here = ships.filter(s => s.stored_at === "here" || s.current);
  // readiness board: best ship per role on board
  const board = el("div", { class: "cag-board" }, ...ROLES.map(([k, label]) => {
    // ties go to the ship made for the role (T7 SAR before the explorer with rescue limpets)
    const best = here.filter(s => s.rating).sort((a, b) => b.rating.roles[k] - a.rating.roles[k]
      || (b.rating.primary === k) - (a.rating.primary === k))[0];
    const n = here.filter(s => s.rating && s.rating.roles[k] >= 4).length;
    return el("button", { class: "cag-role" + (roleFilter === k ? " sel" : ""), onclick: () => { roleFilter = roleFilter === k ? "" : k; store("fis.cag.role", roleFilter); render(); } },
      el("div", { class: "cr-k", text: t(label) }),
      el("div", { class: "cr-v " + (n ? "c-green" : "c-dim"), text: t("{n} ready", { n }) }),
      el("div", { class: "cr-b c-dim", text: best && best.rating.roles[k] ? (best.name || best.type_name) + " " + dots(best.rating.roles[k]) : "–" }));
  }));
  const whereOf = (s) => s.current ? t("in use") : s.stored_at === "here" ? t("on board") : (s.system || s.location || "–") + (s.in_transit ? " ⟫" : "");
  let list = [...ships];
  if (roleFilter) list = list.filter(s => s.rating && s.rating.roles[roleFilter] > 0)
    .sort((a, b) => b.rating.roles[roleFilter] - a.rating.roles[roleFilter]);
  if (onBoardOnly) list = list.filter(s => s.stored_at === "here" || s.current);
  const q = shipQuery.trim().toLowerCase();
  if (q) list = list.filter(s => [s.name, s.type_name, whereOf(s)].some(v => v && String(v).toLowerCase().includes(q)));
  // a clicked column sorts (again: other direction); empty values always last
  const SORT = { ship: s => (s.name || s.type_name || "").toLowerCase(), where: s => s.current ? "0" : s.stored_at === "here" ? "1" : "2" + whereOf(s).toLowerCase(),
    hull: s => s.hull, jump: s => s.jump, cargo: s => s.cargo, fit: s => s.loadout_ts };
  for (const [k] of ROLES) SORT[k] = s => s.rating ? s.rating.roles[k] : null;
  if (SORT[sortKey]) {
    const f = SORT[sortKey];
    list.sort((a, b) => {
      const va = f(a), vb = f(b);
      const ea = va === null || va === undefined || va === "", eb = vb === null || vb === undefined || vb === "";
      if (ea || eb) return ea - eb;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
    });
  }
  const sortBy = (k) => {
    if (sortKey === k) sortDir = -sortDir;
    else { sortKey = k; sortDir = (k === "ship" || k === "where") ? 1 : -1; }   // text A-Z, numbers high first
    store("fis.cag.sort", sortKey); store("fis.cag.dir", sortDir > 0 ? "asc" : "desc");
    render();
  };
  const th = (k, text, extra = {}) => el("th", Object.assign({ text: text + (sortKey === k ? (sortDir > 0 ? " ▲" : " ▼") : ""),
    class: "sort-h" + (extra.class ? " " + extra.class : ""), title: (extra.title ? extra.title + " · " : "") + t("click to sort"),
    onclick: () => sortBy(k) }));
  // role columns: the full name and how the dots are earned on hover
  const head = el("tr", {}, el("th", { text: "" }), th("ship", t("Ship")), th("where", t("Where")),
    ...ROLES.map(([k, l]) => th(k, t(l).slice(0, 4), { title: t(ROLE_HELP[k]), class: "role-h" })),
    th("hull", t("Hull")), th("jump", "ly"), th("cargo", "t"), th("fit", t("Fitting")));
  const search = el("input", { type: "search", class: "cag-q", placeholder: t("filter ships"), value: shipQuery,
    oninput: (e) => { shipQuery = e.target.value; const pos = e.target.selectionStart; render();
      const n = root.querySelector(".cag-q"); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (err) { /* type=search */ } } } });
  const here2 = el("input", { type: "checkbox", checked: onBoardOnly ? true : null,
    onchange: (e) => { onBoardOnly = e.target.checked; store("fis.cag.here", onBoardOnly ? "1" : "0"); render(); } });
  const tools = el("div", { class: "cag-tools" }, search, el("label", { class: "small" }, here2, " " + t("on board only")),
    el("span", { class: "c-dim small", text: t("{n} of {m} ships", { n: list.length, m: ships.length }) }));
  const rows = list.map(s => {
    const r = s.rating;
    const where = whereOf(s);
    return el("tr", { class: (s.current ? "cur " : "") + (s.stored_at === "here" || s.current ? "" : "away") },
      el("td", { class: "c-amber", text: s.current ? "▶" : "" }),
      el("td", {}, el("div", { text: s.name || s.type_name }), el("div", { class: "c-dim small", text: s.name ? s.type_name : "" })),
      el("td", { class: "small", text: where }),
      ...ROLES.map(([k]) => el("td", { class: "rd" + (r && r.primary === k ? " prim" : ""), title: r ? r.why[k] : "",
        text: r ? dots(r.roles[k]) : "" })),
      el("td", { class: "num", text: s.hull !== undefined && s.hull !== null ? Math.round(s.hull * 100) + "%" : "–" }),
      el("td", { class: "num", text: s.jump ? fmt(s.jump, 1) : "–" }),
      el("td", { class: "num", text: s.cargo !== undefined && s.cargo !== null ? fmt(s.cargo, 0) : "–" }),
      el("td", { class: "c-dim small", text: s.loadout_ts ? day(s.loadout_ts) : t("unknown") }));
  });
  const note = el("div", { class: "c-dim small", text: t("Ratings 0–5 from the last known fitting (hover for the reasons). Ships without a fitting were not flown since your journals begin – fly or outfit them once.") });
  const hang = data.hangar;
  return frame(t("AIR WING"), hang ? t("{n} ships · hangar list of {d}", { n: ships.length, d: day(hang.ts) }) : String(ships.length),
    [board, tools, el("div", { class: "scroll cag-list" }, el("table", { class: "ns-tab cag" }, head, ...rows)), note], { cls: "ns-cag", appear: false });
}
