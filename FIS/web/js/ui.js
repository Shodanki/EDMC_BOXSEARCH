// Small DOM and formatting helpers shared by all views.

import { t, locale, lang } from "./i18n.js";

export function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;      // only for trusted static markup
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

/** A chamfered frame: <div.frame><div.frame-in>title + body</div></div> */
export function frame(title, tag, body, opts = {}) {
  const cls = ["frame", opts.kind || "", opts.appear === false ? "" : "appear", opts.cls || ""].join(" ");
  const inner = el("div", { class: "frame-in" });
  if (title) inner.append(el("div", { class: "frame-title" },
    el("h2", { text: title }), tag ? el("span", { class: "tag", text: tag }) : null));
  if (body) inner.append(...[body].flat().filter((x) => x !== null && x !== undefined && x !== false));
  return el("div", { class: cls, style: opts.style }, inner);
}

export function kv(pairs) {
  const box = el("div", { class: "kv" });
  for (const [k, v] of pairs) {
    if (v === null || v === undefined || v === "") continue;
    box.append(el("div", { class: "k", text: k }), el("div", { class: "v" }, v));
  }
  return box;
}

export function num(v, digits = 0, unit = "") {
  if (v === null || v === undefined || Number.isNaN(v)) return el("span", { class: "c-dim", text: "–" });
  const s = fmt(v, digits);
  return el("span", {}, el("span", { class: "num", "data-count": v, "data-digits": digits, text: s }),
            unit ? el("span", { class: "unit", text: unit }) : null);
}

/** Number in the display language (1,234.5 / 1.234,5). */
export function fmt(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number(v).toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** A "⧉" button in a frame's title bar: the view alone in its own window
 *  (second screen; on a tablet just open the same address). Not shown when
 *  the page already is such a window. */
export function withPopout(fr, view) {
  if (new URLSearchParams(location.search).get("solo")) return fr;
  const title = fr.querySelector(".frame-title");
  if (title) title.append(el("button", { class: "popout", text: "⧉",
    title: t("open in its own window (second screen, tablet)"),
    onclick: () => window.open(location.pathname + "?solo=" + view, "fis-" + view, "popup,width=1280,height=860") }));
  return fr;
}

export function chip(text, cls) { return el("span", { class: "chip " + (cls || ""), text }); }

export function hbar(label, value, max, valText, cls = "") {
  const pct = max > 0 ? Math.max(0, Math.min(100, 100 * value / max)) : 0;
  return el("div", { class: "hbar " + cls },
    el("span", { class: "c-dim", text: label }),
    el("div", { class: "track" }, el("i", { style: { width: pct.toFixed(1) + "%" } })),
    el("span", { class: "val", text: valText ?? fmt(value, 1) }));
}

export function tile(k, v, unit) {
  return el("div", { class: "tile" }, el("div", { class: "k", text: k }),
    el("div", { class: "v" }, v, unit ? el("small", { text: " " + unit }) : null));
}

/** Count numbers up from zero when a view appears (toggle: body.motion). */
export function countUp(root) {
  if (!document.body.classList.contains("motion")) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const nodes = root.querySelectorAll(".num[data-count]");
  const t0 = performance.now(), dur = 550;
  const items = [...nodes].map(n => ({ n, to: Number(n.dataset.count), d: Number(n.dataset.digits || 0) }))
    .filter(x => Number.isFinite(x.to) && Math.abs(x.to) > 0);
  if (!items.length) return;
  const step = (tm) => {
    const k = Math.min(1, (tm - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    for (const x of items) x.n.textContent = fmt(x.to * e, x.d);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function ago(ts) {
  if (!ts) return "";
  return minutesAgo(Math.max(0, Math.round((Date.now() / 1000 - ts) / 60)));
}

export function minutesAgo(m) {
  if (m < 1) return t("just now");
  if (m < 90) return t("{n} min ago", { n: m });
  return t("{n} h ago", { n: Math.round(m / 60) });
}

/** "LAST FIX · A 1 d · 3 min ago" from the server's fix record. */
export function fixLabel(fix) {
  if (!fix) return "";
  let s = "LAST FIX · " + (fix.short || "?");
  if (fix.age_min !== null && fix.age_min !== undefined) s += " · " + minutesAgo(Math.floor(fix.age_min));
  return s;
}

/** Planet classes: the journal's English names, short German ones in DE. */
const CLASS_DE = {
  "Earthlike body": "Erdähnlich", "Water world": "Wasserwelt", "Ammonia world": "Ammoniakwelt",
  "High metal content body": "Metallreich (hoch)", "Metal rich body": "Metallreich",
  "Rocky body": "Gestein", "Rocky ice body": "Gestein/Eis", "Icy body": "Eis",
  "Water giant": "Wasserriese", "Gas giant with water based life": "Gasriese (Wasserleben)",
  "Gas giant with ammonia based life": "Gasriese (Ammoniakleben)", "Helium rich gas giant": "Gasriese (heliumreich)",
  "Helium gas giant": "Heliumriese",
};
export function classDe(c) {
  if (!c) return "–";
  if (lang() !== "de") return c;
  if (CLASS_DE[c]) return CLASS_DE[c];
  const m = /^Sudarsky class (\w+) gas giant$/.exec(c);
  return m ? "Gasriese Kl. " + m[1] : c;
}
