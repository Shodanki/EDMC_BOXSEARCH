// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// CARRIER > JUMP PLAN (5.0): the carrier's jumps to a target - planned from
// your own data and EDDiscovery's star database on this PC, or imported
// from Spansh - with tritium, time and the moments to refuel per jump.
// Jumps tick off by themselves when the carrier gets there. Nothing is sent
// to the game: every jump is entered in the carrier's galaxy map by you.

import { getJSON } from "../api.js";
import { copyText, el, fmt, frame } from "../ui.js";
import { t, N_ } from "../i18n.js";
import { dur, hm, timingNote } from "./carrier.js";

const PENDING = "fis.jumpplan.target";      // a target handed over from SYSTEM
const SOURCE = { own: N_("your own data"), "own+edd": N_("your own data + EDDiscovery's star database"),
  spansh: N_("Spansh (imported)") };
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* private window */ } return null; };

let box = null, data = null, msg = "", busy = false, query = "", needSpansh = false, lastTarget = "", paste = "";

/** SYSTEM hands a target over: kept until the plan tab picks it up. */
export function handOver(target) { store(PENDING, JSON.stringify(target)); }

async function post(path, body) {
  const token = new URLSearchParams(location.search).get("token");
  const headers = { "Content-Type": "application/json", "X-FIS-Settings": "1" };
  if (token) headers["X-FIS-Token"] = token;
  const r = await fetch(path, { method: "POST", headers, body: JSON.stringify(body), cache: "no-store" });
  let d = null;
  try { d = await r.json(); } catch (e) { /* no body */ }
  return { status: r.status, data: d || {} };
}

async function load() {
  try { data = await getJSON("/api/jumpplan"); } catch (e) { msg = t("Could not load the plan: {e}", { e: e.message }); }
}

async function plan(target) {
  busy = true; msg = ""; needSpansh = false; lastTarget = target.name || ""; draw();
  try {
    const r = await post("/api/jumpplan/plan", target);
    if (r.status === 404) msg = t("{n} is not in your data nor in EDDiscovery's star database - plan it at Spansh below.", { n: target.name || target.id64 });
    else if (r.status === 409) msg = t("The carrier's position is not known yet - open the carrier management once.");
    else if (r.status !== 200) msg = t("Could not plan: {e}", { e: r.data.error || r.status });
    else if (r.data.here) msg = t("Your carrier is already in {n}.", { n: target.name || "" });
    else if (!r.data.ok) msg = t("No route from known systems: a gap of more than 500 ly. Plan it at Spansh below.");
    needSpansh = r.status === 404 || (r.status === 200 && !r.data.ok && !r.data.here);
  } catch (e) { msg = t("Could not plan: {e}", { e: e.message }); }
  busy = false;
  await load();
  draw();
}

/** The JUMP PLAN tab: a box that fills itself. */
export function planView() {
  box = el("div", { class: "jp" });
  const pend = store(PENDING);
  store(PENDING, null);
  (async () => {
    await load();
    draw();
    if (pend) { try { await plan(JSON.parse(pend)); } catch (e) { /* a broken hand-over */ } }
  })();
  return box;
}

function draw() {
  if (!box) return;
  const has = data && data.plan && data.plan.hops && data.plan.hops.length;
  box.replaceChildren(head(), ...(has ? [summary(), table()] : []), spansh());
}

function head() {
  const input = el("input", { type: "search", class: "jp-q", placeholder: t("target system"), value: query,
    oninput: (e) => { query = e.target.value; },
    onkeydown: (e) => { if (e.key === "Enter" && query.trim()) plan({ name: query.trim() }); } });
  const car = data && data.carrier;
  const rows = [
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Start") }),
      el("span", { class: "c-cyan", text: car && car.system ? car.system : t("carrier position unknown") })),
    el("div", { class: "cag-tools" }, input,
      el("button", { text: busy ? t("planning …") : t("plan"), disabled: busy || null,
        title: t("plan the jumps from your own data, checked with EDDiscovery's star database - nothing goes online"),
        onclick: () => { if (query.trim()) plan({ name: query.trim() }); } }),
      data && data.plan ? el("button", { text: t("clear plan"), disabled: busy || null,
        onclick: async () => { await post("/api/jumpplan/clear", {}); await load(); draw(); } }) : null),
    el("div", { class: "c-dim small", text: t("Or choose a body or ring in SYSTEM: \"carrier target\". The start is always where your carrier is.") }),
  ];
  if (busy) rows.push(el("div", { class: "c-amber small", text: t("Planning - a long route through EDDiscovery's star database can take half a minute.") }));
  if (msg) rows.push(el("div", { class: "c-red small", text: msg }));
  if (data && !data.edd) rows.push(el("div", { class: "c-dim small", text: t("EDDiscovery's star database was not found: only your own systems are used.") }));
  return frame(t("JUMP PLAN"), data && data.plan ? data.plan.target.name : "", rows, { appear: false });
}

function summary() {
  const p = data.plan, tot = data.total;
  const tank = data.carrier ? data.carrier.fuel || 0 : 0;
  const enough = data.need <= tank + (data.hold || 0);
  const line = (k, ...v) => el("div", { class: "ns-row" }, el("div", { class: "ns-k", text: k }), el("div", { class: "ns-v" }, ...v));
  const rows = [
    line(t("Target"), el("span", { class: "c-cyan", text: p.target.name }),
      p.target.body ? el("span", { class: "c-dim", text: "  · " + p.target.body }) : null),
    line(t("Jumps"), el("span", { text: data.arrived ? t("arrived") : t("{l} of {n} to go", { l: data.left, n: p.hops.length }) }),
      el("span", { class: "c-dim", text: p.ideal ? "  · " + t("ideal {n}", { n: p.ideal }) : "" })),
    line(t("Planned with"), el("span", { text: t(SOURCE[p.source] || p.source || "?") }),
      el("span", { class: "c-dim", text: (p.checked_edd && p.source === "own" ? "  · " + t("checked against EDDiscovery: no shorter route") : "")
        + "  · " + new Date(p.created * 1000).toLocaleString() })),
    !data.arrived ? line(t("Tritium"), el("span", { class: enough ? "c-green" : "c-red", text: "~" + fmt(data.need, 0) + " t" }),
      el("span", { class: "c-dim", text: "  · " + t("tank {a} t + hold {b} t", { a: fmt(tank, 0), b: fmt(data.hold || 0, 0) }) })) : null,
    tot ? line(t("Time"), el("span", { text: hm(tot) }),
      el("span", { class: "c-dim", text: "  · " + t("there about {c}", { c: clock(tot.mid) }) })) : null,
    timingNote(data.timing),
  ];
  return frame(t("ROUTE"), p.target.name, rows, { appear: false });
}

function clock(min) {
  return new Date(Date.now() + min * 60000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function note(r) {
  if (r.done) return el("span", { class: "c-green", text: "✓ " + t("arrived {c}", { c: new Date(r.done).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }) });
  const out = [];
  if (r.next) out.push(el("span", { class: "chip mapped", text: t("NEXT") }));
  if (r.refuel) out.push(el("span", { class: r.refuel.short ? "c-red" : "c-amber",
    text: " ⚠ " + (r.refuel.short ? t("{s} t short - not enough tritium", { s: fmt(r.refuel.short, 0) })
      : t("before: at least {m} t into the tank (fill up: {f} t from the hold)", { m: fmt(r.refuel.min, 0), f: fmt(r.refuel.fill, 0) })) }));
  return el("span", {}, ...out);
}

function table() {
  const rows = data.rows;
  const head = el("tr", {}, ...["#", t("system"), "ly", t("tritium"), t("tank after"), t("time"), t("arrival"), ""].map((h) => el("th", { text: h })));
  const body = rows.map((r) => el("tr", { class: (r.done ? "jp-done" : "") + (r.next ? " jp-next" : "") },
    el("td", { class: "c-dim", text: String(r.i) }),
    el("td", {}, el("span", { text: r.name }), r.src === "edd" ? el("span", { class: "c-dim small", title: t("from EDDiscovery's star database"), text: " ·E" }) : null),
    el("td", { class: "num", text: r.ly !== null && r.ly !== undefined ? fmt(r.ly, 1) : "–" }),
    el("td", { class: "num", text: r.need !== undefined ? "~" + fmt(r.need, 0) + " t" : "",
      title: r.spansh_fuel ? t("Spansh: {n} t", { n: r.spansh_fuel }) : "" },
      r.spansh_fuel && r.need !== undefined ? el("div", { class: "c-dim small", text: "Spansh " + r.spansh_fuel + " t" }) : null),
    el("td", { class: "num" + (r.short ? " c-red" : ""), text: r.tank_after !== undefined ? fmt(r.tank_after, 0) + " t" : "" }),
    el("td", { class: "num", text: r.minutes ? "~" + dur(r.minutes) : "" }),
    el("td", { class: "num c-dim", text: r.at ? clock(r.at) : "" }),
    el("td", {}, note(r), r.done ? null : el("button", { class: "jp-copy", text: "⧉", title: t("copy the system name - paste it in the carrier's galaxy map"),
      onclick: (e) => copyText(r.name, e.currentTarget) }))));
  return frame(t("JUMPS"), rows.length === 1 ? t("1 jump") : t("{n} jumps", { n: rows.length }), [
    el("div", { class: "scroll" }, el("table", { class: "ns-tab jp-tab" }, head, ...body)),
    el("div", { class: "c-dim small", text: t("Tritium from the formula fitted on your own jumps, with the tank going down; tritium moved from the hold weighs the same. Ticked off when your carrier arrives (journal). You enter every jump in the game - the FIS sends nothing.") }),
  ], { appear: false });
}

// Spansh: the commander plans there in their own browser; the FIS hands over
// what the router asks for and reads the exported route back (no request
// from the FIS, no file read by it)
async function importRoute(text) {
  busy = true; msg = ""; draw();
  try {
    const r = await post("/api/jumpplan/import", { text });
    if (r.status !== 200) msg = t("Could not read the route: {e}", { e: r.data.error || r.status });
    else { needSpansh = false; paste = "";
      if (r.data.other_start) msg = t("Imported - note: the route starts at {s}, not where your carrier is.", { s: r.data.plan.start.name }); }
  } catch (e) { msg = t("Could not read the route: {e}", { e: e.message }); }
  busy = false;
  await load();
  draw();
}

function spansh() {
  const h = (data && data.spansh) || {};
  const dest = h.destination || lastTarget || query;
  const copyRow = (k, v, tip) => el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: k }),
    el("span", { class: "c-cyan", text: v === null || v === undefined || v === "" ? "–" : String(v) }),
    v === null || v === undefined || v === "" ? null : el("button", { class: "jp-copy", text: "⧉", title: tip || t("copy"),
      onclick: (e) => copyText(String(v), e.currentTarget) }));
  const file = el("input", { type: "file", accept: ".json,.csv,application/json,text/csv",
    onchange: async (e) => { const f = e.target.files && e.target.files[0]; if (f) importRoute(await f.text()); } });
  const area = el("textarea", { class: "jp-paste", rows: 3, placeholder: t("or paste the exported JSON / CSV here"), value: paste,
    oninput: (e) => { paste = e.target.value; } });
  const det = el("details", { class: "jp-spansh" }, el("summary", { text: t("Plan at Spansh instead (online, in your browser)") }),
    el("div", { class: "c-dim small", text: t("Open Spansh's fleet carrier router, enter these values, compute the route and export it (JSON preferred, CSV works). Then choose the file here.") }),
    copyRow(t("Source system"), h.source), copyRow(t("Destination"), dest),
    copyRow(t("Used capacity"), h.used, t("total capacity minus free space of your carrier (CarrierStats)")),
    copyRow(t("Tritium in the tank"), h.tank), copyRow(t("Tritium in the hold"), h.hold),
    el("div", { class: "cag-tools" },
      el("button", { text: t("open Spansh") + " ↗", onclick: () => window.open(h.url || "https://spansh.co.uk/fleet-carrier", "_blank", "noopener") }),
      file),
    area, el("button", { text: t("read pasted route"), disabled: busy || null, onclick: () => { if (paste.trim()) importRoute(paste); } }));
  if (needSpansh) det.open = true;
  return frame("SPANSH", t("optional"), [det], { appear: false });
}
