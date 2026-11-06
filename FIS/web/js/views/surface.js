// SURFACE – where you went on a body and what you found there.
// Track from Status.json (plugin 4.4), marks from the journal, colony
// circles for exobiology. Local map in metres around you / the last fix.

import { getJSON } from "../api.js";
import { el, frame, fmt } from "../ui.js";
import { t, N_ } from "../i18n.js";

let root = null, cv = null, g = null, data = null, info = null, list = null;
let view = { zoom: null, panX: 0, panY: 0 };
let drag = null;

const COL = { ship: "#3EF2E0", srv: "#FFB23E", foot: "#7CFF6B", grid: "rgba(62,242,224,.10)",
  dim: "#6E8F8B", violet: "#B57CFF", red: "#FF4D4D", text: "#CFEDEA" };
const ICON = { touchdown: "▼", liftoff: "▲", srv_out: "◆", srv_in: "◇", disembark: "●", embark: "○",
  bio_log: "✚", bio_sample: "✚", bio_analyse: "✔", material: "■", codex: "★", settlement: "⌂", screenshot: "◉",
  srv_parked: "◆" };
const TONE = { bio_log: "#FFB23E", bio_sample: "#FFB23E", bio_analyse: "#7CFF6B", material: "#B57CFF",
  codex: "#3EF2E0", settlement: "#CFEDEA", touchdown: "#3EF2E0", liftoff: "#6E8F8B" };
const KIND = { touchdown: N_("Touchdown"), liftoff: N_("Lift-off"), srv_out: N_("SRV out"), srv_in: N_("SRV in"),
  disembark: N_("On foot"), embark: N_("Boarded"), srv_parked: N_("SRV parked"), bio_log: N_("Bio 1/3"),
  bio_sample: N_("Bio 2/3"), bio_analyse: N_("Bio 3/3"), material: N_("Material"), codex: N_("Codex"),
  settlement: N_("Settlement"), screenshot: N_("Screenshot") };

export function mount(r) {
  root = r;
  root.classList.add("surface-view");
  const wrap = el("div", { class: "sf-wrap" });
  cv = el("canvas", { class: "sf-map" });
  info = el("div", { class: "sf-info" });
  list = el("div", { class: "sf-list scroll" });
  wrap.append(cv, el("div", { class: "sf-side" }, info, list));
  root.append(frame(t("PLANET · SURFACE"), "", wrap, { cls: "sf-frame" }));
  g = cv.getContext("2d");
  cv.addEventListener("wheel", (e) => { e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.25 : 0.8); }, { passive: false });
  cv.addEventListener("mousedown", (e) => { drag = { x: e.clientX, y: e.clientY, px: view.panX, py: view.panY }; });
  window.addEventListener("mouseup", () => { drag = null; });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    view.panX = drag.px - (e.clientX - drag.x) / view.zoom;
    view.panY = drag.py + (e.clientY - drag.y) / view.zoom;
    draw();
  });
  cv.addEventListener("dblclick", () => { view = { zoom: null, panX: 0, panY: 0 }; draw(); });
  window.addEventListener("resize", () => draw());
}

function zoomBy(f) { view.zoom = Math.max(0.002, Math.min(50, (view.zoom || 0.1) * f)); draw(); }

export async function update(ctx, reason) {
  if (!root) return;
  try { data = await getJSON("/api/surface"); } catch (e) { data = null; }
  render();
}

function extent() {
  const xs = [0], ys = [0];
  for (const s of data.track) for (const [x, y] of s.pts) { xs.push(x); ys.push(y); }
  for (const m of data.marks) if (m.x !== null) { xs.push(m.x); ys.push(m.y); }
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

function niceStep(m) {
  const p = Math.pow(10, Math.floor(Math.log10(m)));
  for (const k of [1, 2, 5, 10]) if (k * p >= m) return k * p;
  return 10 * p;
}

function vehicleLabel(key, v) {
  return key === "parked" ? (v.label || "SRV").toUpperCase() : t("SHIP");
}

function draw() {
  if (!cv || !data) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = Math.max(1, W * dpr); cv.height = Math.max(1, H * dpr);
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!data.center) {
    g.fillStyle = COL.dim; g.font = "13px var(--mono, monospace)";
    g.fillText(data.body ? t("no positions for this body") : t("no landing recorded yet"), 20, 30);
    return;
  }
  if (!view.zoom) {
    const e = data.focus || extent();
    const span = Math.max(200, e.maxX - e.minX, e.maxY - e.minY) * 1.25;
    view.zoom = Math.min(W, H) / span;
    view.panX = (e.minX + e.maxX) / 2; view.panY = (e.minY + e.maxY) / 2;
  }
  const P = (x, y) => [W / 2 + (x - view.panX) * view.zoom, H / 2 - (y - view.panY) * view.zoom];
  // grid + scale
  const step = niceStep(80 / view.zoom);
  g.strokeStyle = COL.grid; g.lineWidth = 1;
  const x0 = view.panX - W / 2 / view.zoom, x1 = view.panX + W / 2 / view.zoom;
  const y0 = view.panY - H / 2 / view.zoom, y1 = view.panY + H / 2 / view.zoom;
  g.beginPath();
  for (let x = Math.floor(x0 / step) * step; x <= x1; x += step) { const [px] = P(x, 0); g.moveTo(px, 0); g.lineTo(px, H); }
  for (let y = Math.floor(y0 / step) * step; y <= y1; y += step) { const [, py] = P(0, y); g.moveTo(0, py); g.lineTo(W, py); }
  g.stroke();
  g.fillStyle = COL.dim; g.font = "11px monospace";
  g.fillText((step >= 1000 ? fmt(step / 1000, 1) + " km" : step + " m") + " / " + t("square") + "   N ↑", 10, H - 10);
  // colony circles
  for (const b of data.bio) {
    if (!b.range_m) continue;
    for (const [x, y] of b.points) {
      const [px, py] = P(x, y);
      g.setLineDash([4, 4]);
      g.strokeStyle = b.done ? "rgba(124,255,107,.35)" : "rgba(255,178,62,.55)";
      g.beginPath(); g.arc(px, py, b.range_m * view.zoom, 0, Math.PI * 2); g.stroke();
      g.setLineDash([]);
    }
  }
  // track
  for (const s of data.track) {
    g.strokeStyle = COL[s.mode] || COL.ship; g.lineWidth = s.mode === "ship" ? 1 : 2;
    g.globalAlpha = s.mode === "ship" ? 0.6 : 0.95;
    g.beginPath();
    s.pts.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? g.lineTo(px, py) : g.moveTo(px, py); });
    g.stroke(); g.globalAlpha = 1;
  }
  // marks
  g.font = "12px monospace";
  for (const m of data.marks) {
    if (m.x === null) continue;
    const [px, py] = P(m.x, m.y);
    g.fillStyle = TONE[m.kind] || COL.text;
    g.fillText(ICON[m.kind] || "·", px - 4, py + 4);
    if (["bio_log", "bio_sample", "codex", "settlement", "material"].includes(m.kind) && view.zoom > 0.05) {
      g.fillStyle = COL.dim; g.fillText((m.label || "").slice(0, 26), px + 8, py - 6);
    }
  }
  // the vehicles to get back to: ring, label, dashed line from you
  for (const [key, colr] of [["parked", COL.srv], ["ship", COL.ship]]) {
    const v = data[key];
    if (!v) continue;
    const [px, py] = P(v.x, v.y);
    if (data.me) {
      const [mx, my] = P(0, 0);
      g.setLineDash([6, 5]); g.strokeStyle = colr; g.globalAlpha = 0.7; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(mx, my); g.lineTo(px, py); g.stroke();
      g.setLineDash([]); g.globalAlpha = 1;
    }
    g.strokeStyle = colr; g.lineWidth = 2;
    g.beginPath(); g.arc(px, py, 11, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.arc(px, py, 17, 0, Math.PI * 2); g.globalAlpha = 0.4; g.stroke(); g.globalAlpha = 1;
    g.fillStyle = colr; g.font = "bold 13px monospace";
    g.fillText((key === "parked" ? "◆ " : "▼ ") + vehicleLabel(key, v), px + 20, py + 4);
  }
  // you
  if (data.me) {
    const [px, py] = P(0, 0);
    const h = ((data.me.heading || 0) * Math.PI) / 180;
    g.save(); g.translate(px, py); g.rotate(h);
    g.fillStyle = COL[data.me.mode] || COL.ship;
    g.beginPath(); g.moveTo(0, -10); g.lineTo(6, 7); g.lineTo(0, 3); g.lineTo(-6, 7); g.closePath(); g.fill();
    g.restore();
  }
}

// B5: suit oxygen, health and temperature while on foot (Status.json)
function lifeSupport(L) {
  const bar = (v, warn) => el("span", { class: "lbar " + (warn ? "warn" : "") },
    el("i", { style: { width: Math.round(100 * (v || 0)) + "%" } }));
  const tempTag = L.very_cold ? t("very cold") : L.very_hot ? t("very hot") : L.cold ? t("cold") : L.hot ? t("hot") : "";
  const temp = L.temp_k !== null && L.temp_k !== undefined ? fmt(L.temp_k, 0) + " K · " + fmt(L.temp_k - 273.15, 0) + " °C" : "–";
  return el("div", { class: "sf-life" },
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Oxygen") }), bar(L.oxygen, L.low_oxygen),
      el("span", { class: L.low_oxygen ? "c-amber" : "", text: L.oxygen === null || L.oxygen === undefined ? "–" : Math.round(L.oxygen * 100) + " %" })),
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Health") }), bar(L.health, L.low_health),
      el("span", { class: L.low_health ? "c-amber" : "", text: L.health === null || L.health === undefined ? "–" : Math.round(L.health * 100) + " %" })),
    el("div", { class: "small " + (L.very_cold || L.very_hot ? "c-amber" : ""), text: t("Temperature") + ": " + temp + (tempTag ? " · " + tempTag : "") }),
    el("div", { class: "small c-dim", text: (L.breathable ? t("breathable atmosphere") : t("no breathable atmosphere"))
      + (L.gravity !== null && L.gravity !== undefined ? " · " + fmt(L.gravity, 2) + " g" : "") }));
}

function render() {
  if (!root) return;
  info.replaceChildren(); list.replaceChildren();
  if (!data || !data.body) {
    info.append(el("div", { class: "empty" }, t("NO SURFACE DATA"), el("br"),
      el("span", { class: "c-dim", text: t("Land on a body – your track and finds appear here.") })));
    draw(); return;
  }
  info.append(el("div", { class: "sf-title" }, el("span", { class: "c-cyan", text: data.short || data.body }),
    el("span", { class: "c-dim", text: " · " + (data.system || "") + (data.gravity_g !== undefined && data.gravity_g !== null ? " · " + fmt(data.gravity_g, 2) + " g" : "") })));
  info.append(el("div", { class: "c-dim small", text: data.here ? t("LIVE · you are here") : t("last visit – not live") }));
  if (data.life) info.append(lifeSupport(data.life));
  if (data.me && data.me.alt !== null && data.me.alt !== undefined)
    info.append(el("div", { class: "small", text: t("Altitude {a} m · heading {h}°", { a: fmt(data.me.alt, 0), h: fmt(data.me.heading, 0) }) }));
  for (const [key, colr] of [["parked", "c-amber"], ["ship", "c-cyan"]]) {
    const v = data[key];
    if (!v) continue;
    const where = v.dist_m !== undefined ? fmt(v.dist_m, 0) + " m · " + fmt(v.bearing, 0) + "°" : t("position saved");
    const what = key === "parked" ? t("{v} PARKED", { v: vehicleLabel(key, v) }) : t("SHIP LANDED");
    info.append(el("div", { class: "sf-park " + colr }, (key === "parked" ? "◆ " : "▼ ") + what + "  " + where));
  }
  for (const b of data.bio) {
    if (b.done) { info.append(el("div", { class: "c-green small", text: "✔ " + t("{s} analysed", { s: b.species }) })); continue; }
    const n = b.samples !== undefined ? b.samples : b.points.length;
    const txt = b.nearest_m !== undefined
      ? b.species + " " + n + "/3 · " + fmt(b.nearest_m, 0) + " m / " + (b.range_m || "?") + " m"
      : b.species + " · " + n + "/3";
    info.append(el("div", { class: b.ok ? "c-green" : "c-amber", text: (b.ok ? "OK  " : "▲  ") + txt }));
  }
  const ms = [...data.marks].reverse().slice(0, 60);
  for (const m of ms) {
    list.append(el("div", { class: "sf-row" },
      el("span", { class: "sf-ic", text: ICON[m.kind] || "·", style: { color: TONE[m.kind] || "" } }),
      el("span", { class: "sf-k", text: KIND[m.kind] ? t(KIND[m.kind]) : m.kind }),
      el("span", { class: "sf-l", text: m.label || "" }),
      el("span", { class: "sf-d c-dim", text: m.dist_m !== undefined ? fmt(m.dist_m, 0) + " m · " + fmt(m.bearing, 0) + "°" : (m.x === null ? t("no position") : "") })));
  }
  draw();
}
