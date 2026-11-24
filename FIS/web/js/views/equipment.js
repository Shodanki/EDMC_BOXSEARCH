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
let group = store("fis.eq.group") || "", place = store("fis.eq.place") || "", ship = store("fis.eq.ship") || "", query = "";

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

function rerender(focusSel) {
  const n0 = focusSel ? box.querySelector(focusSel) : null;
  const pos = n0 ? n0.selectionStart : null;
  draw();
  if (focusSel) { const n = box.querySelector(focusSel); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (e) { /* type=search */ } } }
}

function list() {
  let rows = data.rows;
  if (group) rows = rows.filter(r => r.group === group);
  if (place) rows = rows.filter(r => r.where === place);
  if (ship) rows = rows.filter(r => r.fits.includes(ship)).sort((a, b) => b.better.includes(ship) - a.better.includes(ship));
  const q = query.trim().toLowerCase();
  if (q) rows = rows.filter(r => [r.name, r.code, r.eng, r.where].some(v => v && String(v).toLowerCase().includes(q)));
  const n = rows.reduce((s, r) => s + r.count, 0);
  const tb = (k, label) => el("button", { class: group === k ? "on" : "", "aria-pressed": group === k ? "true" : "false",
    text: t(label), onclick: () => { group = k; store("fis.eq.group", k); draw(); } });
  const placeSel = el("select", { class: "lay-pick eq-pick", onchange: (e) => { place = e.target.value; store("fis.eq.place", place); draw(); } },
    el("option", { value: "", text: t("every place") }),
    ...data.places.map(([w, c]) => el("option", { value: w, selected: w === place ? true : null, text: w + " · " + c })));
  const search = el("input", { type: "search", class: "lay-pick eq-q", placeholder: t("filter modules"), value: query,
    oninput: (e) => { query = e.target.value; rerender(".eq-q"); } });
  const head = el("tr", {}, ...[t("Module"), t("Class"), t("Engineering"), "×", t("Where"), t("Paid"), ship ? t("For {s}", { s: ship }) : t("Fits")]
    .map(h => el("th", { text: h })));
  const body = rows.map(r => el("tr", { class: (ship && r.better.includes(ship) ? "c-green " : "") + (r.place === "carrier" ? "" : "away") },
    el("td", {}, el("span", { text: r.name }), r.mount ? el("span", { class: "c-dim small", text: " · " + t(MOUNT[r.mount]) }) : null),
    el("td", { class: "num", text: r.group === "utility" ? "0" + (r.cls || "") : r.size !== null ? r.size + (r.cls || "") : "–" }),
    el("td", { class: "small" + (r.eng ? " c-violet" : " c-dim"), text: r.eng || "–" }),
    el("td", { class: "num", text: r.count > 1 ? "×" + r.count : "1" }),
    el("td", { class: "small" }, el("span", { text: r.where }),
      r.transit_s ? el("span", { class: "c-amber", text: " ⟫ " + t("{m} min", { m: Math.ceil(r.transit_s / 60) }) }) : null,
      r.hot ? el("span", { class: "chip warn", text: t("hot") }) : null),
    el("td", { class: "num c-dim", title: r.priced < r.count ? t("price known for {n} of {m}", { n: r.priced, m: r.count }) : "", text: cr(r.value) }),
    fitsCell(r)));
  const tools = el("div", { class: "cag-tools" }, el("div", { class: "kc-tabs eq-tabs" }, ...GROUPS.map(([k, l]) => tb(k, l))));
  const tools2 = el("div", { class: "cag-tools" }, placeSel, search,
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
  return frame(t("WHERE IT LIES"), String(data.places.length), data.places.map(([w, c]) => el("button", { class: "eq-place" + (w === place ? " sel" : ""),
    onclick: () => { place = place === w ? "" : w; store("fis.eq.place", place); draw(); } },
  el("span", { class: w === data.carrier ? "c-cyan" : "", text: w }), el("span", { class: "c-dim", text: " · " + c }))), { appear: false });
}
