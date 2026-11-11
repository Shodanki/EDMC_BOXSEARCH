// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
//
// M13: cockpit configuration - which views open in which window on which
// screen, stored in this browser, all opened with one click. Each window is
// a display link (wall-screen mode, no window control). Chromium (Chrome,
// Edge) can place windows on another screen once the page may manage
// windows (the browser asks once, "detect screens"); other browsers place
// them relative to this screen and may ignore the position.

import { el } from "../ui.js";
import { t } from "../i18n.js";

const KEY = "fis.cockpit";
// the tab names, as on the tabs (t() finds the German ones where there are)
const VIEWS = [["briefing", "BRIEFING"], ["surface", "PLANET"], ["tactical", "SYSTEM"], ["galaxy", "GALAXY"],
  ["planet", "PLANET INFO"], ["atlas", "ATLAS"], ["ship", "SHIP"], ["carrier", "CARRIER"], ["mining", "MINING"],
  ["statistics", "STATISTICS"]];
const SCALES = ["0.75", "1", "1.25", "1.5", "2"];

let screens = null;          // ScreenDetailed[] once detected (Chromium)
let opened = [];             // windows opened from here, to close them again
let note = "";

export function load() {
  try {
    const c = JSON.parse(localStorage.getItem(KEY) || "null");
    if (c && Array.isArray(c.windows)) return c;
  } catch (e) { /* none or broken: a fresh one */ }
  return { windows: [] };
}

function save(c) { try { localStorage.setItem(KEY, JSON.stringify(c)); } catch (e) { /* private mode */ } }

export function clampWin(w) {
  const n = (v, d, lo, hi) => { const x = Math.round(Number(v)); return Number.isFinite(x) ? Math.min(hi, Math.max(lo, x)) : d; };
  return {
    view: VIEWS.some(([v]) => v === w.view) ? w.view : "briefing",
    screen: Number.isInteger(w.screen) && w.screen >= 0 ? w.screen : 0,
    x: n(w.x, 0, -10000, 20000), y: n(w.y, 0, -10000, 20000),
    w: n(w.w, 800, 200, 8000), h: n(w.h, 600, 150, 8000),
    scale: SCALES.includes(String(w.scale)) ? String(w.scale) : "1",
  };
}

/** window.open features for one cockpit window; `scr` = {left, top} of its screen. */
export function features(w, scr) {
  const s = scr || { left: 0, top: 0 };
  return "popup,left=" + Math.round(s.left + w.x) + ",top=" + Math.round(s.top + w.y)
    + ",width=" + w.w + ",height=" + w.h;
}

async function detect(redraw) {
  if (!("getScreenDetails" in window)) { note = t("This browser cannot place windows on other screens - they open on this one."); redraw(); return; }
  try {
    const d = await window.getScreenDetails();      // asks once for permission
    screens = d.screens.slice();
    note = t("{n} screens found.", { n: screens.length });
  } catch (e) {
    note = t("Window placement was not allowed - the windows open on this screen.");
  }
  redraw();
}

function screenOf(w) {
  if (screens && screens[w.screen]) return { left: screens[w.screen].availLeft, top: screens[w.screen].availTop };
  return { left: window.screen.availLeft || 0, top: window.screen.availTop || 0 };
}

function openAll(c, urlFor, redraw) {
  let ok = 0, blocked = 0;
  c.windows.forEach((raw, i) => {
    const w = clampWin(raw);
    const win = window.open(urlFor(w), "fis-cockpit-" + i, features(w, screenOf(w)));
    if (win) { ok += 1; opened.push(win); } else blocked += 1;
  });
  note = blocked ? t("{o} opened, {b} blocked - allow pop-ups for this page and click again.", { o: ok, b: blocked })
    : t("{o} windows opened.", { o: ok });
  redraw();
}

function closeAll(redraw) {
  for (const w of opened) { try { w.close(); } catch (e) { /* gone */ } }
  opened = [];
  note = "";
  redraw();
}

/** The COCKPIT frame body. `urlFor(win)` makes the display link of one window. */
export function cockpitRows(urlFor, redraw) {
  const c = load();
  const change = (i, k, v) => { c.windows[i] = clampWin(Object.assign({}, c.windows[i], { [k]: v })); save(c); redraw(); };
  const scrNames = screens ? screens.map((s, i) => (s.label || t("screen {n}", { n: i + 1 })) + (s.isPrimary ? " ★" : ""))
    : [t("this screen")];
  const rows = [el("div", { class: "c-dim small", text: t("Views for extra screens - each opens in its own window, without the window control. Stored in this browser.") })];
  c.windows.forEach((raw, i) => {
    const w = clampWin(raw);
    const num = (k, lab) => el("label", { class: "ck-num" }, el("span", { class: "c-dim", text: lab }),
      el("input", { type: "number", value: String(w[k]), step: "10", onchange: (e) => change(i, k, e.target.value) }));
    rows.push(el("div", { class: "ck-row" },
      el("select", { class: "lay-pick", onchange: (e) => change(i, "view", e.target.value) },
        ...VIEWS.map(([v, l]) => el("option", { value: v, text: t(l), selected: v === w.view ? true : null }))),
      el("select", { class: "lay-pick", title: t("screen"), onchange: (e) => change(i, "screen", Number(e.target.value)) },
        ...scrNames.map((n, k) => el("option", { value: String(k), text: n, selected: k === w.screen ? true : null }))),
      num("x", "x"), num("y", "y"), num("w", t("width")), num("h", t("height")),
      el("select", { class: "lay-pick", title: t("Size"), onchange: (e) => change(i, "scale", e.target.value) },
        ...SCALES.map(v => el("option", { value: v, text: Math.round(Number(v) * 100) + " %", selected: v === w.scale ? true : null }))),
      el("button", { text: "✕", title: t("remove"), onclick: () => { c.windows.splice(i, 1); save(c); redraw(); } })));
  });
  rows.push(el("div", { class: "row-btns" },
    el("button", { text: "+ " + t("window"), onclick: () => {
      const n = c.windows.length;
      c.windows.push(clampWin({ view: VIEWS[(n + 2) % VIEWS.length][0], screen: 0, x: 40 + n * 40, y: 40 + n * 40, w: 900, h: 640 }));
      save(c); redraw();
    } }),
    el("button", { text: t("detect screens"), onclick: () => detect(redraw) }),
    el("button", { text: t("open cockpit"), disabled: c.windows.length ? null : true, onclick: () => openAll(c, urlFor, redraw) }),
    el("button", { text: t("close cockpit"), disabled: opened.length ? null : true, onclick: () => closeAll(redraw) })));
  if (note) rows.push(el("div", { class: "small c-amber", text: note }));
  return rows;
}
