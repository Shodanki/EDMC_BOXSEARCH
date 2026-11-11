// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// Screen size → layout. The FIS runs on a desktop monitor, a second screen,
// a 10" tablet or a phone; the views arrange themselves by the body classes
//   lay-desktop | lay-tablet | lay-phone   and   orient-landscape | orient-portrait
// "Auto" measures the browser window (CSS pixels): ≥ 1400 desktop, ≥ 760
// tablet, below that phone. A choice made by hand is remembered per device
// (localStorage "fis.layout") – a tablet in a dock may want "Tablet" while its
// window is wide.

import { t, N_ } from "./i18n.js";

export const LAYOUTS = [["auto", N_("Auto")], ["desktop", N_("Desktop")], ["tablet", N_("Tablet")], ["phone", N_("Phone")]];
const KEY = "fis.layout";
const NAMES = { desktop: N_("Desktop"), tablet: N_("Tablet"), phone: N_("Phone") };

export function screenInfo() {
  const w = window.innerWidth, h = window.innerHeight;
  return { w, h, dpr: window.devicePixelRatio || 1, touch: (navigator.maxTouchPoints || 0) > 0,
    screenW: window.screen ? window.screen.width : w, screenH: window.screen ? window.screen.height : h };
}

export function detect() {
  const { w } = screenInfo();
  // a page opened in a hidden window reports 0 x 0 - no guess from that;
  // it is measured again once the window is drawn
  if (w < 50) return "desktop";
  return w >= 1400 ? "desktop" : w >= 760 ? "tablet" : "phone";
}

export function chosen() {
  try { const v = localStorage.getItem(KEY); return LAYOUTS.some(([k]) => k === v) ? v : "auto"; }
  catch (e) { return "auto"; }
}

export function current() {
  const c = chosen();
  return c === "auto" ? detect() : c;
}

export function describe() {
  const s = screenInfo();
  return t("{w} × {h} px · scale {d} · {m}", { w: s.w, h: s.h, d: Math.round(s.dpr * 100) / 100, m: t(NAMES[detect()]) })
    + (s.touch ? " · " + t("touch") : "");
}

export function apply() {
  const mode = current();
  const s = screenInfo();
  last = mode + (s.h > s.w ? "p" : "l");
  const b = document.body;
  for (const k of ["desktop", "tablet", "phone"]) b.classList.toggle("lay-" + k, k === mode);
  b.classList.toggle("orient-portrait", s.h > s.w);
  b.classList.toggle("orient-landscape", s.h <= s.w);
  document.documentElement.dataset.layout = mode;
  window.dispatchEvent(new CustomEvent("fis-layout", { detail: { mode } }));
  return mode;
}

export function choose(v) {
  try { localStorage.setItem(KEY, v); } catch (e) { /* private mode */ }
  return apply();
}

/** A select element: Auto (with what was detected) / Desktop / Tablet / Phone. */
export function picker(cls) {
  const sel = document.createElement("select");
  sel.className = cls || "";
  sel.title = t("Layout for this screen");
  const fill = () => {
    sel.replaceChildren(...LAYOUTS.map(([k, label]) => {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = k === "auto" ? t("Auto") + " (" + t(NAMES[detect()]) + ")" : t(label);
      return o;
    }));
    sel.value = chosen();
    sel.title = t("Layout for this screen") + " – " + describe();
  };
  fill();
  sel.addEventListener("change", () => { choose(sel.value); fill(); });
  window.addEventListener("resize", fill);
  return sel;
}

let timer = null, last = "";
function remeasure() {
  clearTimeout(timer);
  timer = setTimeout(() => {           // also turns portrait / landscape
    const s = screenInfo(), sig = current() + (s.h > s.w ? "p" : "l");
    if (sig !== last) { last = sig; apply(); }
  }, 150);
}
window.addEventListener("resize", remeasure);
document.addEventListener("visibilitychange", remeasure);
if (window.ResizeObserver) new ResizeObserver(remeasure).observe(document.documentElement);
