// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// SHIP > MATERIALS (5.1.0, user 24.11.): everything collected, with the
// count - the ship's raw, manufactured and encoded materials (with the change
// since the last login) and what lies in the ship locker on foot.

import { getJSON } from "../api.js";
import { el, fmt, frame } from "../ui.js";
import { t, N_ } from "../i18n.js";

const CATS = [["Raw", N_("RAW")], ["Manufactured", N_("MANUFACTURED")], ["Encoded", N_("ENCODED")]];
const LOCKER = { Items: N_("Items"), Components: N_("Components"), Data: N_("Data"), Consumables: N_("Consumables") };
const SORTS = [["name", N_("by name")], ["count", N_("by count")]];
const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* private window */ } return null; };

let box = null, data = null, busy = false, sort = store("fis.mats.sort") || "name";

export function inventoryView() {
  const fresh = !box;
  if (fresh) box = el("div", { class: "inv" });
  (async () => {
    if (busy) return;
    busy = true;
    try { data = await getJSON("/api/inventory"); } catch (e) { /* keep what was shown */ }
    busy = false;
    draw();
  })();
  if (fresh) draw();
  return box;
}

function sorted(rows) {
  return [...rows].sort(sort === "count" ? (a, b) => b.count - a.count || a.name.localeCompare(b.name) : (a, b) => a.name.localeCompare(b.name));
}

function table(rows, since) {
  return el("table", { class: "ns-tab inv-tab" }, ...sorted(rows).map(r => el("tr", {},
    el("td", { text: r.name }),
    el("td", { class: "num" + (r.cap && r.count >= r.cap ? " c-green" : ""), title: r.cap ? t("grade {g} · at most {c}", { g: r.grade, c: r.cap }) : "",
      text: fmt(r.count, 0) + (r.cap ? " / " + r.cap : "") }),
    since ? el("td", { class: "num small " + (r.since > 0 ? "c-green" : r.since < 0 ? "c-amber" : "c-dim"),
      text: r.since ? (r.since > 0 ? "+" : "") + fmt(r.since, 0) : "" }) : null)));
}

function draw() {
  if (!box) return;
  if (!data) { box.replaceChildren(frame(t("MATERIALS"), "", el("div", { class: "c-dim", text: t("loading …") }))); return; }
  const S = data.ship || { rows: [] };
  const sortSel = el("select", { class: "lay-pick inv-sort", onchange: (e) => { sort = e.target.value; store("fis.mats.sort", sort); draw(); } },
    ...SORTS.map(([k, l]) => el("option", { value: k, selected: k === sort ? true : null, text: t(l) })));
  const total = S.rows.reduce((s, r) => s + r.count, 0);
  const head = el("div", { class: "cag-tools" }, sortSel,
    el("span", { class: "c-dim small", text: S.base_ts
      ? t("{n} materials, {u} units · list of the login {d}, changes since in the right column", { n: S.rows.length, u: fmt(total, 0), d: new Date(S.base_ts).toLocaleString() })
      : t("No material list yet - log in to the game once.") }));
  const note = el("div", { class: "c-dim small", text: t("Counted from the journal since the login. Raw materials stop at their grade's maximum; for manufactured and encoded ones the game does not say when one is full - the next login sets the true count.") });
  const cols = CATS.map(([k, label]) => {
    const rows = S.rows.filter(r => r.cat === k);
    return frame(t(label), t("{n} kinds · {u}", { n: rows.length, u: fmt(rows.reduce((s, r) => s + r.count, 0), 0) }),
      rows.length ? table(rows, true) : el("div", { class: "c-dim small", text: t("none") }), { appear: false, cls: "inv-cat" });
  });
  const other = S.rows.filter(r => !CATS.some(([k]) => k === r.cat));
  const L = data.locker;
  const locker = L && L.rows.length
    ? frame(t("SHIP LOCKER"), t("on foot · as of {d}", { d: L.ts ? new Date(L.ts).toLocaleString() : "?" }),
      Object.keys(LOCKER).filter(c => L.rows.some(r => r.cat === c)).flatMap(c => [
        el("div", { class: "sr-h", text: t(LOCKER[c]) }), table(L.rows.filter(r => r.cat === c), false)]), { appear: false, cls: "inv-locker" })
    : frame(t("SHIP LOCKER"), "", el("div", { class: "c-dim small", text: t("Nothing in the ship locker.") }), { appear: false });
  box.replaceChildren(head, note, el("div", { class: "inv-grid" }, ...cols, locker),
    ...(other.length ? [frame(t("OTHER"), "", table(other, true), { appear: false })] : []));
}
