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

import { getJSON, postJSON } from "../api.js";
import { copyText, el, fmt, frame, meter, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";
import { planView } from "./jumpplan.js";

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
let nearby = null, nearbyMsg = "";      // H2: carriers near you, asked at Spansh on a click
let root = null, data = null, known = null, knownQuery = "", knownMsg = "", showAllSeen = false, roleFilter = store("fis.cag.role") || "";
// E4: ship list sortable by every column, with a text filter and "on board only"
let sortKey = store("fis.cag.sort") || "", sortDir = store("fis.cag.dir") === "asc" ? 1 : -1;
let shipQuery = "", onBoardOnly = store("fis.cag.here") === "1";
// with a carrier of your own, the known carriers get a tab of their own (11.11.)
// CT1 (18.11.): the own carrier's trade gets a tab of its own, before the known carriers
// 5.0 JUMP PLAN: the carrier's jumps to a target, a tab of its own
let tab = ["known", "trade", "plan"].includes(store("fis.carrier.tab")) ? store("fis.carrier.tab") : "own";
// what a visited carrier offered when you docked (StationServices, lower case)
const KC_SERVICE = { refuel: N_("Refuel"), repair: N_("Repair"), rearm: N_("Rearm"), commodities: N_("Commodities"),
  shipyard: N_("Shipyard"), outfitting: N_("Outfitting"), blackmarket: N_("Secure warehouse"),
  exploration: N_("Universal Cartographics"), vistagenomics: N_("Vista Genomics"), bartender: N_("Bar"),
  pioneersupplies: N_("Pioneer Supplies"), voucherredemption: N_("Redemption office"), carrierfuel: N_("Tritium depot") };

export function mount(r) { root = r; root.classList.add("carrier-view"); }

export async function update(ctx, reason) {
  if (!root) return;
  if (reason === "show" && store("fis.jumpplan.target")) tab = "plan";
  if (reason !== "show" && reason !== "data" && data) return;
  const [d, k] = await Promise.all([getJSON("/api/carrier").catch(() => null),
    getJSON("/api/carriers/known").catch(() => null)]);
  data = d; known = k;
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

// K4: other carriers you know - favourites first (★), then the ones you
// docked at or started something from, then the newest FSS sightings
const HOW = { docked: N_("docked"), sighted: N_("seen in the FSS"), jump: N_("jumped with you aboard") };

function since(ts) { const ms = Date.parse(ts || ""); return isNaN(ms) ? "?" : age((Date.now() - ms) / 1000); }

async function star(c, on, note) {
  knownMsg = "";
  try {
    const body = { callsign: c.callsign, on };
    if (note !== undefined) body.note = note;
    await postJSON("/api/carriers/favourite", body);
    known = await getJSON("/api/carriers/known");
  } catch (e) { knownMsg = t("Could not save: {e}", { e: e.message }); }
  render();
}

async function lookup(c, btn) {
  btn.disabled = true; btn.textContent = "…";
  try {
    await postJSON("/api/carriers/lookup", { callsign: c.callsign });
    knownMsg = "";
  } catch (e) {
    knownMsg = t("Online lookup failed: {e}", { e: e.message || e });
  }
  try { known = await getJSON("/api/carriers/known"); } catch (e) { /* keep the old list */ }
  render();
}

// H2: the carriers Spansh knows near you - one request on a click, kept a day per region
async function findNearby(btn) {
  btn.disabled = true; btn.textContent = "…";
  try { nearby = await postJSON("/api/carriers/nearby", {}); nearbyMsg = ""; }
  catch (e) { nearbyMsg = t("Online lookup failed: {e}", { e: e.message || e }); }
  render();
}

function nearbyRow(c) {
  const key = (c.access || "").toLowerCase().replace(/[^a-z]/g, "");
  const svc = (c.services || []).filter(s => KC_SERVICE[s]).map(s => t(KC_SERVICE[s]));
  const fav = !!(known && known.favourites.some(f => f.callsign === c.callsign));
  return el("div", { class: "kc-row" + (fav ? " fav" : "") },
    el("button", { class: "fav-star" + (fav ? " on" : ""), text: fav ? "★" : "☆",
      title: fav ? t("remove from favourites") : t("mark as favourite"), onclick: () => star(c, !fav) }),
    el("div", { class: "kc-main" },
      el("div", {}, el("span", { class: "c-cyan", text: c.callsign }),
        el("span", { class: "c-dim", text: "  " + fmt(c.distance, 1) + " ly" }),
        c.access ? el("span", { class: "chip" + (key === "all" ? " mapped" : ""), text: ACCESS[key] ? t(ACCESS[key]) : c.access }) : null),
      el("div", { class: "small" }, el("span", { text: c.system || "?" }),
        el("span", { class: "c-dim", text: "  " + t("reported {d}", { d: day(c.updated) }) })),
      svc.length ? el("div", { class: "small" }, el("span", { class: "c-dim", text: t("services") + ": " }), svc.join(" · ")) : null),
    el("div", { class: "kc-act" },
      c.id64 ? el("button", { text: t("open system"), title: t("show the system with everything known about it"),
        onclick: () => window.open(location.pathname + "?solo=tactical&system=" + c.id64, "fis-detail", "popup,width=1280,height=860") }) : null,
      el("button", { text: t("copy system"), disabled: c.system ? null : true,
        title: t("copy the system name - paste it in the galaxy map to plot the jump"),
        onclick: (e) => copyText(c.system, e.currentTarget) })));
}

function nearbyRows() {
  const rows = [el("div", { class: "sr-h", text: t("NEAR YOU - ONLINE") }),
    el("div", { class: "kc-act" }, el("button", { text: t("find carriers near me"),
      title: t("ask Spansh once for the carriers within 100 ly of you - at most once a day per region"),
      onclick: (e) => findNearby(e.currentTarget) }))];
  if (nearbyMsg) rows.push(el("div", { class: "c-red small", text: nearbyMsg }));
  if (nearby && nearby.carriers) {
    if (!nearby.carriers.length) rows.push(el("div", { class: "c-dim small", text: t("Spansh knows no carrier within 100 ly.") }));
    rows.push(...nearby.carriers.map(nearbyRow));
    rows.push(el("div", { class: "c-dim small", text: t("Spansh, asked {d}: where someone last reported each carrier - it may have jumped since.", { d: since(nearby.checked) }) }));
  }
  return rows;
}

function carrierRow(c) {
  const what = [];
  if (c.docked_n) what.push(t("docked {n}×", { n: c.docked_n }));
  for (const s of (c.started || []).slice(-2).reverse()) {
    what.push((s.kind === "cg" ? t("CG") : t("mission")) + ": " + (s.name || "?")
      + (s.commodity ? " · " + s.commodity + (s.count ? " " + fmt(s.count, 0) + " t" : "") : "")
      + (s.to ? " → " + s.to : ""));
  }
  const m = c.market;
  const buys = m && m.buys && m.buys.length ? m.buys.slice(0, 3).map(b => b.name + " " + fmt(b.demand, 0) + " t").join(" · ") : "";
  // A1 docking access, the services you found there, the whole market to unfold
  const a = c.access;
  const accessEl = a ? el("span", { class: "chip " + (a.state === "dock" ? "mapped" : a.state === "none" ? "warn" : ""),
    title: t("docking access: {a}", { a: a.access || "–" }) + (a.ts ? " · " + day(a.ts) : ""),
    text: a.state === "dock" ? t("dockable") : a.state === "none" ? t("no docking for you") : t("friends/squadron only") }) : null;
  const svc = (c.services || []).filter(s => KC_SERVICE[s.toLowerCase()]).map(s => t(KC_SERVICE[s.toLowerCase()]));
  const svcEl = svc.length ? el("div", { class: "small" }, el("span", { class: "c-dim", text: t("services") + ": " }), svc.join(" · "),
    el("span", { class: "c-dim", text: "  (" + t("when you docked, {d}", { d: day(c.services_ts) }) + ")" })) : null;
  const goods = (lst, k, unit) => (lst || []).map(g => el("div", { class: "kc-good" },
    el("span", { text: g.name || g.key }), el("span", { class: "num", text: fmt(g[k], 0) + " t" }),
    el("span", { class: "num c-dim", text: g.price ? fmt(g.price, 0) + " Cr" : "" })));
  const marketEl = m && ((m.buys && m.buys.length) || (m.sells && m.sells.length)) ? el("details", { class: "small kc-market" },
    el("summary", { text: t("market of {d}", { d: day(m.ts) }) + (m.system ? " · " + m.system : "") }),
    m.buys && m.buys.length ? el("div", {}, el("div", { class: "c-green", text: t("bought") }), ...goods(m.buys, "demand")) : null,
    m.sells && m.sells.length ? el("div", {}, el("div", { class: "c-amber", text: t("sold") }), ...goods(m.sells, "stock")) : null) : null;
  const openBtn = c.system_id64 ? el("button", { text: t("open system"), title: t("show the system with everything known about it"),
    onclick: () => window.open(location.pathname + "?solo=tactical&system=" + c.system_id64, "fis-detail", "popup,width=1280,height=860") }) : null;
  const btn = el("button", { class: "fav-star" + (c.favourite ? " on" : ""), text: c.favourite ? "★" : "☆",
    title: c.favourite ? t("remove from favourites") : t("mark as favourite"), onclick: () => star(c, !c.favourite) });
  // K5: a favourite can be looked up at Spansh - on a click, once every 6 h
  const on = c.online;
  const onLine = on ? el("div", { class: "small" + (on.found ? "" : " c-dim") },
    el("span", { class: "c-violet", text: "Spansh: " }),
    on.found ? (on.system || "?") + (on.updated ? "  (" + t("reported {d}", { d: day(on.updated) }) + ")" : "")
      : t("not known there"),
    el("span", { class: "c-dim", text: "  · " + t("asked {d}", { d: since(on.checked) }) })) : null;
  const lookBtn = c.favourite ? el("button", { text: t("online"), title: t("look this favourite up at Spansh (once every 6 hours)"),
    onclick: (e) => lookup(c, e.currentTarget) }) : null;
  const noteBtn = c.favourite ? el("button", { text: "✎", title: t("note"),
    onclick: () => { const v = window.prompt(t("Note for {c}", { c: c.callsign }), c.note || ""); if (v !== null) star(c, true, v); } }) : null;
  return el("div", { class: "kc-row" + (c.favourite ? " fav" : "") }, btn,
    el("div", { class: "kc-main" },
      el("div", {}, el("span", { class: "c-cyan", text: c.name || "?" }), el("span", { class: "c-dim", text: "  " + c.callsign }),
        accessEl ? " " : null, accessEl,
        c.note ? el("span", { class: "c-amber small", text: "  " + c.note }) : null),
      el("div", { class: "small" }, el("span", { text: c.system || t("position unknown") }),
        el("span", { class: "c-dim", text: "  " + t(HOW[c.how] || "seen in the FSS") + " " + since(c.ts)
          + (c.dist_ly !== null && c.dist_ly !== undefined ? " · " + fmt(c.dist_ly, 1) + " ly" : "")
          + (c.from_store ? " · " + t("stored") : "") })),
      what.length ? el("div", { class: "small c-dim", text: what.join(" · ") }) : null,
      buys && !marketEl ? el("div", { class: "small" }, el("span", { class: "c-green", text: t("bought") + ": " }), buys,
        el("span", { class: "c-dim", text: "  (" + t("market of {d}", { d: day(m.ts) }) + ")" })) : null,
      svcEl, marketEl, onLine),
    el("div", { class: "kc-act" }, lookBtn, noteBtn, openBtn,
      el("button", { text: t("copy system"), disabled: c.system ? null : true,
        title: t("copy the system name - paste it in the galaxy map to plot the jump"),
        onclick: (e) => copyText(c.system, e.currentTarget) })));
}

function knownCarriers() {
  const k = known;
  const q = knownQuery.trim().toLowerCase();
  const match = (c) => !q || [c.callsign, c.name, c.system, c.note].some(v => v && String(v).toLowerCase().includes(q));
  const fav = k.favourites.filter(match), met = k.met.filter(match), seen = k.sighted.filter(match);
  const rows = [];
  const search = el("input", { type: "search", class: "cag-q kc-q", placeholder: t("filter carriers"), value: knownQuery,
    oninput: (e) => { knownQuery = e.target.value; const pos = e.target.selectionStart; render();
      const n = root.querySelector(".kc-q"); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (err) { /* type=search */ } } } });
  rows.push(el("div", { class: "cag-tools" }, search));
  if (knownMsg) rows.push(el("div", { class: "c-red small", text: knownMsg }));
  rows.push(el("div", { class: "sr-h", text: t("FAVOURITES") }));
  rows.push(...(fav.length ? fav.map(carrierRow) : [el("div", { class: "c-dim small", text: t("None yet - mark a carrier with ☆.") })]));
  if (met.length) { rows.push(el("div", { class: "sr-h", text: t("DOCKED OR STARTED FROM") })); rows.push(...met.map(carrierRow)); }
  if (seen.length) {
    rows.push(el("div", { class: "sr-h", text: t("SEEN IN PASSING") }));
    rows.push(...(showAllSeen ? seen : seen.slice(0, 8)).map(carrierRow));
    if (seen.length > 8) rows.push(el("button", { text: showAllSeen ? t("fewer") : t("show {n} more", { n: seen.length - 8 }),
      onclick: () => { showAllSeen = !showAllSeen; render(); } }));
  }
  rows.push(el("div", { class: "c-dim small", text: t("Last known positions from your own journals; the market is the one you last opened there. Online only when you click it for a favourite (Spansh, the place someone last reported).") }));
  rows.push(...nearbyRows());
  return frame(t("KNOWN CARRIERS"), t("{f} favourites · {n} known", { f: k.counts.favourites, n: k.counts.known }), rows, { cls: "ns-known", appear: false });
}

function render() {
  if (!root) return;
  root.replaceChildren();
  if (data && data.visiting) root.append(visiting());
  if (!data || data.empty) {
    root.append(frame(t("CARRIER"), "", el("div", { class: "empty" }, t("NO CARRIER DATA"), el("br"),
      el("span", { class: "c-dim", text: t("No carrier of your own known yet - your ships are listed below. If you own one, open the carrier management once.") }))));
    if (known) root.append(knownCarriers());
    if (data && data.fleet && data.fleet.length) root.append(airWing());
    return;
  }
  {
    const tb = (k, label) => el("button", { class: tab === k ? "on" : "", "aria-pressed": tab === k ? "true" : "false", text: label,
      onclick: () => { tab = k; store("fis.carrier.tab", k); render(); } });
    root.append(el("div", { class: "kc-tabs" }, tb("own", t("MY CARRIER")),
      tb("plan", t("JUMP PLAN")),
      data.trade ? tb("trade", t("CARRIER TRADE")) : null,
      known ? tb("known", t("KNOWN CARRIERS") + " · " + known.counts.known) : null));
  }
  if (tab === "plan") { root.append(planView()); return; }
  if (known && tab === "known") { root.append(knownCarriers()); return; }
  if (data.trade && tab === "trade") { root.append(trade()); return; }
  root.append(el("div", { class: "ns-grid" },
    el("div", { class: "ns-col" }, ident(), position(), tritium()),
    el("div", { class: "ns-col" }, hold(), finance(), services())));
  root.append(airWing());
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
      meter(pctTank, 100, pctTank < 25 ? "warn" : ""),          // TH6: the tank's share for the themes
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
      tr.with_hold ? el("div", { class: "c-dim small", text: t("Full 500-ly jumps; the tank takes {m} t, so move tritium from the hold about every {k} jumps.", { m: fmt(tr.tank_max, 0), k: Math.max(1, Math.floor(tr.tank_max / (tr.per_max_jump || 1))) }) }) : null,
      el("span", { class: "c-dim small", text: "  " + t("Frontier data, {a}", { a: age(tr.hold.age_s) }) }))
      : el("div", { class: "c-dim small", text: t("Tritium in the carrier's hold comes with EDMC's Frontier data (Companion API) - none yet.") }),
    tr.time && tr.time.range ? line(t("Time for the range"), el("span", { text: hm(tr.time.range) })) : null,
    tr.time && tr.time.trip ? line(t("Time to your route's end"), el("span", { text: hm(tr.time.trip) })) : null,
    tr.time ? timingNote(tr.time.timing) : null,
    el("div", { class: "c-dim small", text: tr.learnt && tr.learnt.learnt
      ? t("Formula learnt from {n} of your jumps (±{e} t), it follows every new jump: {f}", { n: tr.learnt.n, e: fmt(tr.learnt.max_err || 0, 0), f: tr.formula })
      : t("Default formula: {f}", { f: tr.formula }) + " · " + t("learnt from 5 jumps of 20 ly and more - {n} so far", { n: tr.learnt ? tr.learnt.n : 0 }) }),
  ], { appear: false });
}

// 5.0 JUMP PLAN: "~3 h 35 min (3 h 20 – 4 h 30)" from minutes
export function dur(m) {
  m = Math.round(m || 0);
  return m < 60 ? t("{m} min", { m }) : t("{h} h {m} min", { h: Math.floor(m / 60), m: m % 60 });
}
export function hm(tt) {
  return "~" + dur(tt.mid) + (tt.hi > tt.lo ? " (" + dur(tt.lo) + " – " + dur(tt.hi) + ")" : "")
    + " · " + (tt.jumps === 1 ? t("1 jump") : t("{n} jumps", { n: tt.jumps }));
}
export function timingNote(tm) {
  const c = tm.countdown;
  return el("div", { class: "c-dim small", text: (c.learnt
    ? t("Countdown ~{m} min ({a}–{b}), learnt from {n} of your jumps", { m: fmt(c.mid, 1), a: fmt(c.lo, 1), b: fmt(c.hi, 1), n: c.n })
    : t("Countdown ~{m} min (no own jump yet)", { m: fmt(c.mid, 0) }))
    + " · " + t("cooldown {m} min after each jump (public value)", { m: fmt(tm.cooldown, 0) })
    + (tm.fastest_next ? " · " + t("your fastest next jump order: {m} min after arrival", { m: fmt(tm.fastest_next, 1) }) : "") });
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

// ------------------------------------------------------------ CT1: carrier trade
const CR = (v) => v === null || v === undefined ? "–" : v >= 1e6 ? fmt(v / 1e6, 1) + " M Cr" : fmt(v, 0) + " Cr";
const SVC = { ok: N_("open"), unmanned: N_("not manned"), unavailable: N_("not installed"), closed: N_("closed") };
function svc(st) { return st ? el("span", { class: st === "ok" ? "c-green" : "c-dim", text: SVC[st] ? t(SVC[st]) : st }) : null; }

function trade() {
  const T = data.trade, C = T.capi;
  const left = [demand(T), C ? tradeMarket(C.market) : null];
  const right = [C ? tradeBar(C.bar) : null, C ? tradeYard(C) : null, tradeHistory(T.history)];
  if (!C) left.push(frame(t("MARKET"), "", el("div", { class: "c-dim", text: t("Orders, stock, the bar, shipyard and outfitting come with EDMC's Frontier data (Companion API) - none yet. Below: the orders from your journal.") }), { appear: false }));
  return el("div", { class: "ns-grid ct-grid" }, el("div", { class: "ns-col" }, ...left), el("div", { class: "ns-col" }, ...right));
}

// what is still wanted: open purchase orders, market and bar
function demand(T) {
  const D = T.demand, C = T.capi;
  if (!C) return null;
  const rows = [line(t("Still wanted"), el("span", { class: D.units ? "c-amber" : "c-dim", text: D.units ? fmt(D.units, 0) + " " + t("units") : t("nothing") }),
    D.cr ? el("span", { class: "c-dim", text: "  · " + CR(D.cr) }) : null)];
  for (const r of D.rows) rows.push(el("div", { class: "lg-row" }, el("span", { text: r.name + (r.where === "bar" ? " · " + t("bar") : "") }),
    meter(r.delivered, r.total || 1), el("span", { class: "num", text: fmt(r.delivered, 0) + " / " + fmt(r.total, 0) + " · " + CR(r.price) })));
  rows.push(el("div", { class: "c-dim small", text: t("Frontier data, {a}. Purchase orders with what is delivered so far; the rest is reserved from the carrier's balance.", { a: age(C.age_s) }) }));
  return frame(t("OPEN DEMAND"), D.cr ? CR(D.cr) : "", rows, { appear: false });
}

function orderTable(sales, buys) {
  if (!sales.length && !buys.length) return el("div", { class: "c-dim", text: t("No orders set.") });
  return el("table", { class: "ns-tab" },
    el("tr", {}, ...["", t("good"), t("amount"), t("price"), t("value")].map(h => el("th", { text: h }))),
    ...sales.map(r => el("tr", {}, el("td", { class: "c-green", text: t("sells") }), el("td", { text: r.name + (r.black ? " ⚠" : "") }),
      el("td", { class: "num", text: fmt(r.stock, 0) }), el("td", { class: "num", text: CR(r.price) }), el("td", { class: "num", text: CR(r.value) }))),
    ...buys.map(r => el("tr", {}, el("td", { class: "c-amber", text: t("buys") }), el("td", { text: r.name + (r.black ? " ⚠" : "") }),
      el("td", { class: "num", text: fmt(r.outstanding, 0) + " / " + fmt(r.total, 0) }), el("td", { class: "num", text: CR(r.price) }),
      el("td", { class: "num", text: CR(r.open_cr) }))));
}

function tradeMarket(M) {
  const F = M.finances || {};
  const rows = [line(t("Market"), svc(M.status)), orderTable(M.sales, M.purchases),
    line(t("Cargo for sale"), fmt(M.for_sale_t, 0) + " t", el("span", { class: "c-dim", text: "  · " + t("not for sale") + " " + fmt(M.not_for_sale_t, 0) + " t" })),
    line(t("Cargo value"), CR(F.cargo_value)),
    line(t("Market profit (all time)"), el("span", { class: "c-green", text: CR(F.profit) }))];
  if (M.black && (M.black.profit || M.black.for_sale || M.black.purchase_orders))
    rows.push(line(t("Secure warehouse profit"), CR(M.black.profit)));
  const stock = M.stock.filter(r => r.stock || r.demand);
  if (stock.length) {
    rows.push(el("div", { class: "ns-sub", text: t("AS VISITORS SEE IT") }));
    rows.push(el("table", { class: "ns-tab" },
      el("tr", {}, ...[t("good"), t("pieces"), t("demand"), t("we sell at"), t("we buy at")].map(h => el("th", { text: h }))),
      ...stock.slice(0, 20).map(r => el("tr", {}, el("td", { text: r.name }), el("td", { class: "num", text: fmt(r.stock, 0) }),
        el("td", { class: "num", text: fmt(r.demand, 0) }), el("td", { class: "num", text: r.buy ? CR(r.buy) : "–" }),
        el("td", { class: "num", text: r.sell ? CR(r.sell) : "–" })))));
  }
  return frame(t("MARKET"), "", rows, { appear: false });
}

function tradeBar(B) {
  const F = B.finances || {};
  const rows = [line(t("Bar"), svc(B.status)), orderTable(B.sales, B.purchases),
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Locker") }), meter(B.used, B.capacity || 1),
      el("span", { text: fmt(B.used, 0) + " / " + fmt(B.capacity, 0) })),
    line(t("Bar profit (all time)"), el("span", { class: F.profit ? "c-green" : "c-dim", text: CR(F.profit) }))];
  if (B.profit_history.some(v => v)) rows.push(line(t("Profit per week"), el("span", { class: "c-dim", text: B.profit_history.map(v => CR(v)).join(" · ") })));
  return frame(t("BAR"), t("on-foot goods"), rows, { appear: false });
}

function tradeYard(C) {
  const S = C.shipyard, O = C.outfitting;
  const rows = [line(t("Shipyard"), svc(S.status), el("span", { class: "c-dim", text: "  · " + t("{n} ship packs", { n: S.packs }) }))];
  if (S.ships.length) rows.push(el("table", { class: "ns-tab" }, ...S.ships.map(r => el("tr", {}, el("td", { text: r.name }),
    el("td", { class: "num", text: fmt(r.stock, 0) }), el("td", { class: "num", text: CR(r.price) })))));
  else rows.push(el("div", { class: "c-dim small", text: t("No ships for sale.") }));
  rows.push(line(t("Outfitting"), svc(O.status), el("span", { class: "c-dim", text: "  · " + t("{n} module packs", { n: O.packs }) })));
  rows.push(line(t("In stock"), t("{u} modules of {k} kinds", { u: fmt(O.units, 0), k: O.kinds - O.bundled }), el("span", { class: "c-dim", text: "  · " + CR(O.value) })));
  if (O.modules.length) rows.push(el("div", { class: "scroll ct-mods" }, el("table", { class: "ns-tab" },
    el("tr", {}, ...[t("module"), t("pieces"), t("price")].map(h => el("th", { text: h }))),
    ...O.modules.map(r => el("tr", {}, el("td", { text: r.name }), el("td", { class: "num", text: fmt(r.stock, 0) }),
      el("td", { class: "num", text: CR(r.price) }))))));
  if (O.bundled) rows.push(el("div", { class: "c-dim small", text: t("{n} bays come with the packs (no stock).", { n: O.bundled }) }));
  return frame(t("SHIPYARD & OUTFITTING"), "", rows, { appear: false });
}

const ORDER_KIND = { buy: [N_("buy order"), "c-amber"], sell: [N_("sell order"), "c-green"], cancel: [N_("cancelled"), "c-dim"], other: [N_("changed"), "c-dim"] };
function tradeHistory(H) {
  const rows = H.length ? [el("table", { class: "ns-tab" }, ...H.slice(0, 12).map(h => el("tr", {},
    el("td", { class: "c-dim", text: day(h.ts) }), el("td", { class: ORDER_KIND[h.kind][1], text: t(ORDER_KIND[h.kind][0]) }),
    el("td", { text: h.name || "?" }), el("td", { class: "num", text: h.qty ? fmt(h.qty, 0) : "" }),
    el("td", { class: "num", text: h.price ? CR(h.price) : "" }))))]
    : [el("div", { class: "c-dim", text: t("No trade orders in your journals.") })];
  return frame(t("ORDER HISTORY"), t("journal"), rows, { appear: false });
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
      el("td", { class: "num", text: s.jump ? fmt(s.jump, 1) : "–" }, fsdBadge(s.fsd)),
      el("td", { class: "num", text: s.cargo !== undefined && s.cargo !== null ? fmt(s.cargo, 0) : "–" }),
      el("td", { class: "c-dim small", text: s.loadout_ts ? day(s.loadout_ts) : t("unknown") }));
  });
  const fsdNote = el("div", { class: "c-dim small", text: t("FSD: the grade of the drive's engineering; ↑ an unlocked engineer already took your drive higher (hover). Only a hint from your own engineering.") });
  const note = el("div", { class: "c-dim small", text: t("Ratings 0–5 from the last known fitting (hover for the reasons). Ships without a fitting were not flown since your journals begin – fly or outfit them once.") });
  const hang = data.hangar;
  return frame(t("AIR WING"), hang ? t("{n} ships · hangar list of {d}", { n: ships.length, d: day(hang.ts) }) : String(ships.length),
    [board, tools, el("div", { class: "scroll cag-list" }, el("table", { class: "ns-tab cag" }, head, ...rows)), note, fsdNote], { cls: "ns-cag", appear: false });
}

// EN1: the FSD's grade under the jump range, with an arrow when an unlocked
// engineer already engineered your drive higher - a hint, never advice
function fsdBadge(f) {
  if (!f) return null;
  const g = f.grade ? "G" + f.grade : t("stock");
  const h = f.hint;
  const tip = (f.grade ? t("FSD {g} by {e}", { g, e: f.engineer || "?" }) + (f.experimental ? " · " + f.experimental : "") : t("FSD not engineered"))
    + (h ? "\n" + t("{n} gave your drive G{to} before - unlocked", { n: h.engineers.join(", "), to: h.to }) : "");
  return el("div", { class: "small " + (h ? "c-amber" : "c-dim"), title: tip, text: g + (h ? " ↑" : "") });
}
