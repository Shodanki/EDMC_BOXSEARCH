// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// CARRIER > EQUIPMENT (EQ1, 5.1.0): the modules in storage - on your carrier
// or at the stations where they lie - by category and slot, how many, where,
// the price paid, the engineering, and which of your ships each one fits.
// A ship picked on the right shows only what fits it, the better-than-fitted
// first; EDSY and Coriolis open with the ship's fitting (links, on a click).

import { getJSON } from "../api.js";
import { el, fmt, frame } from "../ui.js";
import { t, N_ } from "../i18n.js";

const GROUPS = [["", N_("all")], ["core", N_("core")], ["optional", N_("optional")], ["hardpoint", N_("hardpoints")],
  ["utility", N_("utility")], ["armour", N_("armour")]];
const MOUNT = { fixed: N_("fixed"), gimbal: N_("gimballed"), turret: N_("turreted") };
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* private window */ } return null; };

let box = null, data = null, busy = false;
let group = store("fis.eq.group") || "", ship = store("fis.eq.ship") || "";
// user 24.11.: module, class, engineering and place as choices, no search;
// each list offers only what the other choices leave, with the count
const clsOf = (r) => r.group === "utility" ? "0" + (r.cls || "") : r.size !== null ? r.size + (r.cls || "") : "–";
const PICKS = [["name", N_("every module"), r => r.name], ["cls", N_("every class"), clsOf],
  ["eng", N_("any engineering"), r => r.bp || ""], ["where", N_("every place"), r => r.where]];
let sel = (() => { try { return JSON.parse(store("fis.eq.sel")) || {}; } catch (e) { return {}; } })();
function pick(k, v) { sel = Object.assign({}, sel, { [k]: v }); store("fis.eq.sel", JSON.stringify(sel)); draw(); }
function engOk(r, v) { return v === "+" ? !!r.bp : v === "-" ? !r.bp : r.bp === v; }
function filtered(skip) {
  let rows = data.rows;
  if (group) rows = rows.filter(r => r.group === group);
  if (ship) rows = rows.filter(r => r.fits.includes(ship));
  for (const [k, , f] of PICKS) {
    const v = sel[k];
    if (!v || k === skip) continue;
    rows = rows.filter(r => k === "eng" ? engOk(r, v) : f(r) === v);
  }
  return rows;
}
function pickSel([k, all, f]) {
  const counts = new Map();
  for (const r of filtered(k)) { const v = f(r); if (v) counts.set(v, (counts.get(v) || 0) + r.count); }
  const v = sel[k] || "";
  if (v && !counts.has(v) && !(k === "eng" && (v === "+" || v === "-"))) counts.set(v, 0);
  const opts = [...counts.entries()].sort((a, b) => k === "cls" ? b[0].localeCompare(a[0], undefined, { numeric: true }) : a[0].localeCompare(b[0]));
  const extra = k === "eng" ? [el("option", { value: "+", selected: v === "+" ? true : null, text: t("engineered") }),
    el("option", { value: "-", selected: v === "-" ? true : null, text: t("not engineered") })] : [];
  return el("select", { class: "lay-pick eq-pick eq-" + k, onchange: (e) => pick(k, e.target.value) },
    el("option", { value: "", text: t(all) }), ...extra,
    ...opts.map(([o, c]) => el("option", { value: o, selected: o === v ? true : null, text: o + " · " + c })));
}

export function equipmentView() {
  const fresh = !box;
  if (fresh) box = el("div", { class: "eq" });
  (async () => {
    if (busy) return;
    busy = true;
    try { data = await getJSON("/api/equipment"); } catch (e) { /* keep what was shown */ }
    busy = false;
    draw();
  })();
  if (fresh) draw();
  return box;
}

function cr(v) { return !v ? "–" : v >= 1e6 ? fmt(v / 1e6, 1) + " M" : fmt(v, 0); }
function day(ts) { return ts ? String(ts).slice(0, 10) : "?"; }

function draw() {
  if (!box) return;
  if (!data) { box.replaceChildren(frame(t("EQUIPMENT"), "", el("div", { class: "c-dim", text: t("loading …") }))); return; }
  if (data.empty) {
    box.replaceChildren(frame(t("EQUIPMENT"), "", el("div", { class: "empty" }, t("NO STORAGE LIST YET"), el("br"),
      el("span", { class: "c-dim", text: t("Open Outfitting > Storage once at any station or on your carrier - the game then writes the list of every stored module.") }))));
    return;
  }
  box.replaceChildren(el("div", { class: "ns-grid eq-grid" },
    el("div", { class: "ns-col" }, list()), el("div", { class: "ns-col" }, ships(), places())));
}

function list() {
  const rows = [...filtered()];
  if (ship) rows.sort((a, b) => b.better.includes(ship) - a.better.includes(ship));
  const n = rows.reduce((s, r) => s + r.count, 0);
  const tb = (k, label) => el("button", { class: group === k ? "on" : "", "aria-pressed": group === k ? "true" : "false",
    text: t(label), onclick: () => { group = k; store("fis.eq.group", k); draw(); } });
  const head = el("tr", {}, ...[t("Module"), t("Class"), t("Engineering"), "×", t("Where"), t("Paid"), ship ? t("For {s}", { s: ship }) : t("Fits")]
    .map(h => el("th", { text: h })));
  const body = rows.map(r => el("tr", { class: (ship && r.better.includes(ship) ? "c-green " : "") + (r.place === "carrier" ? "" : "away") },
    el("td", {}, el("span", { text: r.name }), r.mount ? el("span", { class: "c-dim small", text: " · " + t(MOUNT[r.mount]) }) : null),
    el("td", { class: "num", text: clsOf(r) }),
    el("td", { class: "small" + (r.eng ? " c-violet" : " c-dim"), text: r.eng || "–" }),
    el("td", { class: "num", text: r.count > 1 ? "×" + r.count : "1" }),
    el("td", { class: "small" }, el("span", { text: r.where }),
      r.transit_s ? el("span", { class: "c-amber", text: " ⟫ " + t("{m} min", { m: Math.ceil(r.transit_s / 60) }) }) : null,
      r.hot ? el("span", { class: "chip warn", text: t("hot") }) : null),
    el("td", { class: "num c-dim", title: r.priced < r.count ? t("price known for {n} of {m}", { n: r.priced, m: r.count }) : "", text: cr(r.value) }),
    fitsCell(r)));
  const tools = el("div", { class: "cag-tools" }, el("div", { class: "kc-tabs eq-tabs" }, ...GROUPS.map(([k, l]) => tb(k, l))));
  const any = PICKS.some(([k]) => sel[k]);
  const tools2 = el("div", { class: "cag-tools" }, ...PICKS.map(pickSel),
    any ? el("button", { text: t("reset") + " ✕", onclick: () => { sel = {}; store("fis.eq.sel", "{}"); draw(); } }) : null,
    ship ? el("button", { text: t("all ships") + " ✕", onclick: () => { ship = ""; store("fis.eq.ship", ""); draw(); } }) : null,
    el("span", { class: "c-dim small", text: t("{n} of {m} modules", { n, m: data.count }) }));
  const note = el("div", { class: "c-dim small", text: t("From the storage list of {d} ({s}) and what you stored, retrieved, sold or sent off since. Open Outfitting > Storage to refresh it. Fits by slot and size from each ship's last fitting - the game may still refuse a module in some hulls. ▲ better than fitted: the same kind, larger, a better class or engineered.",
    { d: day(data.list_ts), s: data.list_at || "?" }) });
  return frame(t("EQUIPMENT IN STORAGE"), data.carrier ? t("{n} modules · on board {c}", { n: data.count, c: data.carrier }) : t("{n} modules", { n: data.count }),
    [tools, tools2, el("div", { class: "scroll eq-list" }, el("table", { class: "ns-tab eq-tab" }, head, ...body)), note], { cls: "eq-store", appear: false });
}

function fitsCell(r) {
  if (ship) return el("td", { class: "small", text: r.better.includes(ship) ? "▲ " + t("better than fitted") : t("fits") });
  if (!r.fits.length) return el("td", { class: "c-dim small", text: t("no own ship") });
  return el("td", { class: "small", title: r.fits.join(", ") + (r.better.length ? "\n▲ " + r.better.join(", ") : "") },
    el("span", { text: t("{n} ships", { n: r.fits.length }) }),
    r.better.length ? el("span", { class: "c-green", text: " · ▲ " + r.better.length }) : null);
}

function ships() {
  const rows = data.ships.map(s => el("div", { class: "eq-ship" + (s.name === ship ? " sel" : "") },
    el("button", { class: "eq-sn", title: t("show what fits this ship"),
      onclick: () => { ship = ship === s.name ? "" : s.name; store("fis.eq.ship", ship); draw(); } },
      el("span", { class: s.current ? "c-cyan" : "", text: (s.current ? "▶ " : "") + s.name }),
      el("span", { class: "c-dim small", text: "  " + (s.type_name || s.type) })),
    el("div", { class: "small" },
      el("span", { class: "c-dim", text: t("{n} fit", { n: s.fits_n }) }),
      s.better_n ? el("span", { class: "c-green", text: " · ▲ " + t("{n} better", { n: s.better_n }) }) : null,
      el("span", { class: "eq-links" },
        el("a", { href: s.edsy, target: "_blank", rel: "noopener noreferrer", text: "EDSY" }), " · ",
        el("a", { href: s.coriolis, target: "_blank", rel: "noopener noreferrer", text: "Coriolis" })))));
  return frame(t("YOUR SHIPS"), String(data.ships.length), [...rows,
    el("div", { class: "c-dim small", text: t("EDSY and Coriolis open with the ship's last fitting, in your browser, only on a click - the FIS sends nothing.") })],
  { cls: "eq-ships", appear: false });
}

function places() {
  return frame(t("WHERE IT LIES"), String(data.places.length), data.places.map(([w, c]) => el("button", { class: "eq-place" + (w === sel.where ? " sel" : ""),
    onclick: () => pick("where", sel.where === w ? "" : w) },
  el("span", { class: w === data.carrier ? "c-cyan" : "", text: w }), el("span", { class: "c-dim", text: " · " + c }))), { appear: false });
}
