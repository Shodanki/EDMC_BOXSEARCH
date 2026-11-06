// GALAXY – your way through the galaxy and the survey around it.
// Top view: galactic x to the right, z up (towards the core); y (height)
// shows in the tooltip. Layers can be switched; the path is coloured by age
// (old = violet, new = cyan). Wheel zooms at the cursor, drag pans, double
// click fits everything; a click on a system opens it in SYSTEM (new tab).
// 2D | 3D: the same data in Three.js (galaxy3d.js), loaded on demand; if the
// CDN is not reachable the view stays 2D. The replay slider draws the path
// jump by jump, in both modes.

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";

const LAYERS = [["path", N_("flight path")], ["carrier", N_("carrier")], ["systems", N_("systems")],
  ["boxels", N_("boxels")], ["spheres", N_("spheres")], ["finds", N_("finds")], ["navroute", N_("route")]];
const SPANS = [[0, N_("all time")], [90, N_("90 days")], [30, N_("30 days")], [7, N_("7 days")], [1, N_("24 hours")]];
const MC = "abcdefgh";
const C = { cyan: "#3EF2E0", amber: "#FFB23E", green: "#7CFF6B", violet: "#B57CFF", red: "#FF4D4D",
  dim: "#6E8F8B", text: "#CFEDEA", grid: "rgba(62,242,224,.07)" };
const FIND_COL = { guardian: "#4FA3FF", nonhuman: "#7CFF6B", brain: "#B57CFF" };
const FIND_NAME = { guardian: N_("Guardian site"), nonhuman: N_("non-human site"), brain: N_("Brain Trees") };
const BOX_NAME = { closed: N_("closed"), open: N_("open"), unchecked: N_("never checked") };

let root = null, cv = null, g = null, side = null, data = null, hover = null;
let view = { scale: null, cx: 0, cz: 0 };
let drag = null, picks = [];
const on = JSON.parse(localStorage.getItem("fis.gal.layers") || "null") ||
  { path: true, carrier: true, systems: true, boxels: true, spheres: true, finds: true, navroute: true };
let days = Number(localStorage.getItem("fis.gal.days") || "0");
let mc = localStorage.getItem("fis.gal.mc") || "";
let mode = new URLSearchParams(location.search).has("2d") ? "2d" : (localStorage.getItem("fis.gal.mode") || "2d");
let g3 = null, g3load = null, ov = null, stage = null, replay = 1, playTimer = null;
let ui = {};                     // toolbar elements

export function mount(r) {
  root = r;
  root.classList.add("galaxy-view");
  cv = el("canvas", { class: "gal-map" });
  ov = el("canvas", { class: "gal-ov", style: { display: "none" } });
  stage = el("div", { class: "gal-stage" }, cv, ov);
  side = el("div", { class: "gal-side scroll" });
  root.append(el("div", { class: "gal-grid" }, withPopout(frame(t("GALAXY"), "", [tools(), stage], { cls: "gal-main", appear: false }), "galaxy"), side));
  g = cv.getContext("2d");
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [wx, wz] = toWorld(e.offsetX, e.offsetY);
    view.scale *= e.deltaY < 0 ? 1.25 : 0.8;
    view.scale = Math.max(0.0005, Math.min(400, view.scale));
    const [nx, nz] = toWorld(e.offsetX, e.offsetY);       // keep the point under the cursor
    view.cx += wx - nx; view.cz += wz - nz; draw();
  }, { passive: false });
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: view.cx, cz: view.cz, moved: false }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => {
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      view.cx = drag.cx - dx / view.scale; view.cz = drag.cz + dy / view.scale; draw(); return;
    }
    const p = nearest(e.offsetX, e.offsetY);
    if (p !== hover) { hover = p; cv.style.cursor = p && p.id ? "pointer" : ""; draw(); renderSide(); }
  });
  cv.addEventListener("pointerup", () => {
    if (drag && !drag.moved && hover && hover.id) openPick(hover);
    drag = null;
  });
  cv.addEventListener("dblclick", () => { fit(); draw(); });
  new ResizeObserver(() => draw()).observe(cv);
  if (mode === "3d") setMode("3d"); else applyMode();
}

function openPick(p) { window.open("/?system=" + p.id + "#tactical", "_blank"); }

// ------------------------------------------------------------ toolbar: 2D | 3D, camera, replay
function tools() {
  const pick = (m) => () => { localStorage.setItem("fis.gal.mode", m); setMode(m); };
  ui.b2 = el("button", { text: "2D", onclick: pick("2d") });
  ui.b3 = el("button", { text: "3D", onclick: pick("3d") });
  ui.cams = el("span", { class: "gal-cams" },
    el("button", { text: t("above"), title: t("look down on the galactic plane"), onclick: () => g3 && g3.view("top") }),
    el("button", { text: t("side"), title: t("look along the galactic plane"), onclick: () => g3 && g3.view("side") }));
  ui.play = el("button", { text: "▶", title: t("replay the flight path"), onclick: togglePlay });
  ui.slider = el("input", { type: "range", min: "0", max: "1000", value: "1000", class: "gal-replay",
    title: t("replay the flight path"), oninput: (e) => { stopPlay(); setReplay(Number(e.target.value) / 1000); } });
  ui.head = el("span", { class: "gal-head small c-dim" });
  ui.eng = el("span", { class: "gal-eng small c-dim" });
  const bar = el("div", { class: "gal-tools" }, el("span", { class: "gal-seg" }, ui.b2, ui.b3), ui.cams, ui.play, ui.slider, ui.head, ui.eng);
  return bar;
}

async function setMode(m) {
  mode = m;
  if (m === "3d" && !g3) {
    ui.eng.textContent = t("loading 3D …"); ui.eng.className = "gal-eng small c-dim";
    try {
      g3load = g3load || Promise.race([import("./galaxy3d.js"),
        new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 8000))]);
      const mod = await g3load;
      if (!g3) g3 = mod.createGalaxy3D(stage, ov, { t, label, pick: openPick });
      g3.setReplay(replay);
      if (data) g3.setData(data, on);
      ui.eng.textContent = "";
    } catch (err) {
      g3load = null; mode = "2d";
      ui.eng.textContent = t("2D · offline (Three.js not reachable)"); ui.eng.className = "gal-eng small c-amber";
    }
  }
  applyMode();
}

function applyMode() {
  const three = mode === "3d" && !!g3;
  ui.b2.setAttribute("aria-pressed", three ? "false" : "true");
  ui.b3.setAttribute("aria-pressed", three ? "true" : "false");
  ui.cams.style.display = three ? "" : "none";
  if (!cv) return;
  cv.style.display = three ? "none" : "";
  ov.style.display = three ? "" : "none";
  if (g3) { g3.canvas.style.display = three ? "" : "none"; if (three) g3.redraw(); }
  if (!three) draw();
  if (side && data) renderSide();
}

function view3d() { return mode === "3d" && g3; }
function refit(what) { if (view3d()) g3.view(what === "you" ? "me" : what || "all"); else { fit(what); draw(); } }

function setReplay(k) {
  replay = Math.max(0, Math.min(1, k));
  ui.slider.value = String(Math.round(replay * 1000));
  if (g3) g3.setReplay(replay);
  const h = head();
  ui.head.textContent = replay < 1 && h ? h.name + (h.t ? " · " + new Date(h.t * 1000).toLocaleDateString() : "") : "";
  if (!view3d()) draw();
}
function stopPlay() { if (playTimer) { clearInterval(playTimer); playTimer = null; ui.play.textContent = "▶"; } }
function togglePlay() {
  if (playTimer) { stopPlay(); return; }
  if (replay >= 1) setReplay(0);
  const start = performance.now(), k0 = replay;
  ui.play.textContent = "❚❚";
  playTimer = setInterval(() => {                       // the whole period in 20 s
    const k = k0 + (performance.now() - start) / 20000;
    setReplay(k);
    if (k >= 1) stopPlay();
  }, 50);
}
function head() {
  if (!data || !data.path.length) return null;
  return data.path[Math.round((data.path.length - 1) * replay)];
}

export async function update(ctx, reason) {
  if (!root) return;
  if (reason !== "show" && reason !== "data" && data) return;
  const qs = new URLSearchParams();
  if (days) qs.set("days", String(days));
  if (mc !== "") qs.set("mc", mc);
  try { data = await getJSON("/api/galaxy?" + qs.toString()); } catch (e) { data = null; }
  if (data && view.scale === null) fit();
  if (data && g3) g3.setData(data, on);
  if (replay < 1) setReplay(replay);
  renderSide(); draw();
}

// ------------------------------------------------------------ geometry
function size() { return [cv.clientWidth || 1, cv.clientHeight || 1]; }
function toScreen(x, z) { const [W, H] = size(); return [W / 2 + (x - view.cx) * view.scale, H / 2 - (z - view.cz) * view.scale]; }
function toWorld(px, py) { const [W, H] = size(); return [view.cx + (px - W / 2) / view.scale, view.cz - (py - H / 2) / view.scale]; }

function fit(what) {
  if (!data) return;
  let pts = [];
  if (what === "you" && data.you) { view.cx = data.you.x; view.cz = data.you.z; view.scale = 4; return; }
  if (what === "sphere" && data.active) {
    const [W, H] = size(); view.cx = data.active.x; view.cz = data.active.z;
    view.scale = Math.min(W, H) / (data.active.r * 2.6); return;
  }
  pts = data.path.map(p => [p.x, p.z]);
  if (data.you) pts.push([data.you.x, data.you.z]);
  for (const s of data.spheres) pts.push([s.x - s.r, s.z - s.r], [s.x + s.r, s.z + s.r]);
  if (!pts.length) pts = data.systems.map(s => [s.x, s.z]);
  if (!pts.length) { view.cx = 0; view.cz = 0; view.scale = 0.05; return; }
  const xs = pts.map(p => p[0]), zs = pts.map(p => p[1]);
  const [W, H] = size();
  const w = Math.max(20, Math.max(...xs) - Math.min(...xs)), h = Math.max(20, Math.max(...zs) - Math.min(...zs));
  view.cx = (Math.max(...xs) + Math.min(...xs)) / 2; view.cz = (Math.max(...zs) + Math.min(...zs)) / 2;
  view.scale = Math.min(W / (w * 1.15), H / (h * 1.15));
}

function nearest(px, py) {
  let best = null, bd = 12 * 12;
  for (const p of picks) { const d = (p.sx - px) ** 2 + (p.sy - py) ** 2; if (d < bd) { bd = d; best = p; } }
  return best;
}

function niceStep(ly) { const p = Math.pow(10, Math.floor(Math.log10(ly))); for (const k of [1, 2, 5, 10]) if (k * p >= ly) return k * p; return 10 * p; }

// ------------------------------------------------------------ drawing
function draw() {
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1, [W, H] = size();
  cv.width = Math.max(1, W * dpr); cv.height = Math.max(1, H * dpr);
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  picks = [];
  if (!data || W < 40 || H < 40 || view3d()) return;
  if (view.scale === null) fit();
  const vis = (x, z, m = 20) => { const [sx, sy] = toScreen(x, z); return sx > -m && sx < W + m && sy > -m && sy < H + m; };
  // grid
  const step = niceStep(90 / view.scale);
  const [x0, z1] = toWorld(0, 0), [x1, z0] = toWorld(W, H);
  g.strokeStyle = C.grid; g.lineWidth = 1; g.beginPath();
  for (let x = Math.floor(x0 / step) * step; x <= x1; x += step) { const [sx] = toScreen(x, 0); g.moveTo(sx, 0); g.lineTo(sx, H); }
  for (let z = Math.floor(z0 / step) * step; z <= z1; z += step) { const [, sy] = toScreen(0, z); g.moveTo(0, sy); g.lineTo(W, sy); }
  g.stroke();
  // boxels of the active sphere
  if (on.boxels && data.boxels.length && data.boxel_size) {
    // seen from above, the boxels of one column (different heights) lie on
    // top of each other: one square per column, coloured by its share of
    // closed / open boxels, "closed/total" written in when there is room
    const s = data.boxel_size * view.scale;
    const cols = new Map();
    for (const b of data.boxels) {
      const k = b.x + "," + b.z;
      let c = cols.get(k);
      if (!c) { c = { x: b.x, z: b.z, closed: 0, open: 0, unchecked: 0, list: [] }; cols.set(k, c); }
      c[b.status]++; c.list.push(b);
    }
    for (const c of cols.values()) {
      if (!vis(c.x, c.z, s)) continue;
      const [sx, sy] = toScreen(c.x, c.z), n = c.list.length;
      const gF = c.closed / n, aF = c.open / n;
      if (gF) { g.fillStyle = `rgba(124,255,107,${(.08 + .32 * gF).toFixed(3)})`; g.fillRect(sx - s / 2, sy - s / 2, s, s); }
      if (aF) { g.fillStyle = `rgba(255,178,62,${(.06 + .22 * aF).toFixed(3)})`; g.fillRect(sx - s / 2, sy - s / 2, s, s); }
      g.strokeStyle = c.open ? "rgba(255,178,62,.45)" : c.closed === n ? "rgba(124,255,107,.5)" : "rgba(110,143,139,.22)";
      g.lineWidth = 1; g.strokeRect(sx - s / 2 + .5, sy - s / 2 + .5, s - 1, s - 1);
      if (s > 34) { g.fillStyle = c.closed === n ? C.green : c.open ? C.amber : C.dim; g.font = "10px monospace"; g.fillText(c.closed + "/" + n, sx - s / 2 + 4, sy + s / 2 - 4); }
      if (s > 10) picks.push({ sx, sy, kind: "boxel", c });
    }
  }
  // spheres
  if (on.spheres) {
    for (const sp of data.spheres) {
      const act = data.active && Math.abs(sp.x - data.active.x) < .01 && Math.abs(sp.z - data.active.z) < .01;
      const [sx, sy] = toScreen(sp.x, sp.z);
      g.setLineDash(act ? [] : [5, 5]); g.strokeStyle = act ? C.cyan : "rgba(62,242,224,.4)"; g.lineWidth = act ? 1.6 : 1;
      g.beginPath(); g.arc(sx, sy, sp.r * view.scale, 0, Math.PI * 2); g.stroke(); g.setLineDash([]);
      g.fillStyle = act ? C.cyan : C.dim; g.font = "11px monospace";
      g.fillText(sp.label, sx + sp.r * view.scale * .72 + 4, sy - sp.r * view.scale * .72);
    }
  }
  // systems
  if (on.systems) {
    const small = view.scale < 1.2;
    for (const s of data.systems) {
      if (!s.v && small) continue;                 // far out: only where you have been
      if (!vis(s.x, s.z)) continue;
      const [sx, sy] = toScreen(s.x, s.z);
      g.fillStyle = s.u ? C.violet : s.v ? (s.f ? C.green : "rgba(124,255,107,.6)") : "rgba(110,143,139,.45)";
      const r = s.v ? 2.2 : 1.3;
      g.fillRect(sx - r, sy - r, r * 2, r * 2);
      picks.push({ sx, sy, kind: "system", s, id: s.id });
    }
  }
  // carrier path
  if (on.carrier && data.carrier.length > 1) {
    g.strokeStyle = "rgba(255,178,62,.75)"; g.lineWidth = 1.2; g.setLineDash([2, 4]); g.beginPath();
    data.carrier.forEach((c, i) => { const [sx, sy] = toScreen(c.x, c.z); i ? g.lineTo(sx, sy) : g.moveTo(sx, sy); });
    g.stroke(); g.setLineDash([]);
    for (const c of data.carrier) { const [sx, sy] = toScreen(c.x, c.z); g.fillStyle = C.amber; g.fillRect(sx - 2.5, sy - 2.5, 5, 5); picks.push({ sx, sy, kind: "carrier", c }); }
  }
  // flight path, coloured by age
  if (on.path && data.path.length > 1) {
    const t0 = data.path[0].t || 0, t1 = data.path[data.path.length - 1].t || 1, span = Math.max(1, t1 - t0);
    g.lineWidth = 1.3;
    const last = Math.round((data.path.length - 1) * replay);
    for (let i = 1; i <= last; i++) {
      const a = data.path[i - 1], b = data.path[i];
      if (b.kind === "login" && Math.hypot(b.x - a.x, b.z - a.z) > 100) continue;   // other session, no flight
      const k = ((b.t || t0) - t0) / span;
      g.strokeStyle = `rgba(${Math.round(181 - 119 * k)},${Math.round(124 + 118 * k)},${Math.round(255 - 31 * k)},${.35 + .6 * k})`;
      const [ax, ay] = toScreen(a.x, a.z), [bx, by] = toScreen(b.x, b.z);
      g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke();
    }
    data.path.forEach((p, i) => { if (i > last) return; const [sx, sy] = toScreen(p.x, p.z); picks.push({ sx, sy, kind: "jump", p, id: p.id64 }); });
    if (replay < 1) {                       // replay head
      const [sx, sy] = toScreen(data.path[last].x, data.path[last].z);
      g.strokeStyle = "#FFFFFF"; g.lineWidth = 1.5; g.beginPath(); g.arc(sx, sy, 6, 0, Math.PI * 2); g.stroke();
    }
  }
  // finds
  if (on.finds) {
    for (const f of data.finds) {
      if (!vis(f.x, f.z)) continue;
      const [sx, sy] = toScreen(f.x, f.z);
      f.kinds.forEach((k, i) => { g.fillStyle = FIND_COL[k] || C.text; g.font = "13px monospace"; g.fillText("◆", sx - 5 + i * 9, sy - 6); });
      picks.push({ sx, sy, kind: "find", f, id: f.id });
    }
  }
  // plotted route
  if (on.navroute && data.navroute.length > 1) {
    g.strokeStyle = C.amber; g.lineWidth = 1.5; g.setLineDash([6, 4]); g.beginPath();
    data.navroute.forEach((h, i) => { const [sx, sy] = toScreen(h.x, h.z); i ? g.lineTo(sx, sy) : g.moveTo(sx, sy); });
    g.stroke(); g.setLineDash([]);
  }
  // Sol: in view a point, otherwise an arrow at the edge
  const [solx, soly] = toScreen(0, 0);
  g.font = "11px monospace";
  if (solx > 0 && solx < W && soly > 0 && soly < H) { g.fillStyle = "#FFF4E8"; g.beginPath(); g.arc(solx, soly, 3, 0, Math.PI * 2); g.fill(); g.fillText("Sol", solx + 6, soly - 4); }
  else {
    const ang = Math.atan2(soly - H / 2, solx - W / 2), ex = W / 2 + Math.cos(ang) * (W / 2 - 24), ey = H / 2 + Math.sin(ang) * (H / 2 - 24);
    g.fillStyle = C.dim; g.save(); g.translate(ex, ey); g.rotate(ang); g.beginPath(); g.moveTo(8, 0); g.lineTo(-6, -5); g.lineTo(-6, 5); g.closePath(); g.fill(); g.restore();
    const d = data.you ? Math.hypot(data.you.x, data.you.y, data.you.z) : null;
    g.fillText("Sol" + (d ? " " + fmt(d, 0) + " ly" : ""), ex + (Math.cos(ang) > 0 ? -70 : 10), ey + (Math.sin(ang) > 0 ? -10 : 16));
  }
  // you
  if (data.you) {
    const [sx, sy] = toScreen(data.you.x, data.you.z);
    g.strokeStyle = "#FFFFFF"; g.lineWidth = 1.5;
    g.beginPath(); g.arc(sx, sy, 7, 0, Math.PI * 2); g.moveTo(sx - 11, sy); g.lineTo(sx + 11, sy); g.moveTo(sx, sy - 11); g.lineTo(sx, sy + 11); g.stroke();
  }
  // hover label
  if (hover) {
    const txt = label(hover);
    g.font = "12px monospace"; const w = g.measureText(txt).width + 10;
    const x = Math.min(W - w - 4, hover.sx + 10), y = Math.max(16, hover.sy - 12);
    g.fillStyle = "rgba(5,12,13,.88)"; g.fillRect(x, y - 13, w, 18);
    g.strokeStyle = "rgba(62,242,224,.4)"; g.strokeRect(x, y - 13, w, 18);
    g.fillStyle = C.text; g.fillText(txt, x + 5, y);
  }
  // scale bar
  const bar = niceStep(120 / view.scale);
  g.fillStyle = C.dim; g.font = "11px monospace";
  g.fillRect(12, H - 14, bar * view.scale, 2);
  g.fillText(fmt(bar, 0) + " ly   ↑ " + t("core"), 12, H - 20);
}

function label(p) {
  const y = (o) => " · y " + fmt(o.y, 0);
  if (p.kind === "system") return p.s.n + y(p.s) + (p.s.u ? " · " + t("only known to us") : p.s.v ? " · " + t("visited") : "");
  if (p.kind === "jump") return p.p.name + y(p.p) + (p.p.t ? " · " + new Date(p.p.t * 1000).toLocaleDateString() : "");
  if (p.kind === "carrier") return t("carrier") + ": " + p.c.name;
  if (p.kind === "find") return p.f.name + " · " + p.f.kinds.map(k => t(FIND_NAME[k] || k)).join(", ");
  if (p.kind === "boxel") {
    const keys = p.c.list.filter(b => b.key).map(b => b.key);
    return (keys[0] || t("boxel")) + (keys.length > 1 ? " +" + (keys.length - 1) : "") + " · "
      + t("{c} closed · {o} open · {u} never checked", { c: p.c.closed, o: p.c.open, u: p.c.unchecked });
  }
  return "";
}

// ------------------------------------------------------------ side panel
function renderSide() {
  side.replaceChildren();
  if (!data) { side.append(frame(t("GALAXY"), "", el("div", { class: "empty", text: t("no data yet") }))); return; }
  const st = data.stats;
  const period = st.first ? new Date(st.first * 1000).toLocaleDateString() + " – " + new Date(st.last * 1000).toLocaleDateString() : "";
  const daySel = el("select", { class: "lay-pick", onchange: (e) => { days = Number(e.target.value); localStorage.setItem("fis.gal.days", String(days)); view.scale = null; update(null, "data"); } },
    ...SPANS.map(([v, l]) => el("option", { value: String(v), text: t(l) })));
  daySel.value = String(days);
  side.append(frame(t("FLIGHT LOG"), period, [
    el("div", { class: "gal-big" }, el("span", { class: "c-cyan", text: fmt(st.ly, 0) + " ly" }), el("span", { class: "c-dim", text: "  " + t("{n} jumps · {s} systems", { n: st.jumps, s: st.systems }) })),
    el("div", { class: "gal-row" }, el("span", { class: "c-dim", text: t("Period") }), daySel),
    data.you ? el("div", { class: "small c-dim", text: t("You: {n} · {d} ly from Sol", { n: data.you.name, d: fmt(Math.hypot(data.you.x, data.you.y, data.you.z), 0) }) }) : null,
  ], { appear: false }));
  // layers
  side.append(frame(t("LAYERS"), "", el("div", { class: "gal-layers" }, ...LAYERS.map(([k, l]) => el("label", { class: "gal-lay" },
    el("input", { type: "checkbox", checked: on[k] ? true : null, onchange: (e) => {
      on[k] = e.target.checked; localStorage.setItem("fis.gal.layers", JSON.stringify(on));
      if (g3) g3.setLayers(on);
      draw();
    } }),
    " " + t(l)))), { appear: false }));
  // survey sphere
  if (data.active) {
    const n = { closed: 0, open: 0, unchecked: 0 };
    for (const b of data.boxels) n[b.status]++;
    const mcSel = el("select", { class: "lay-pick", onchange: (e) => { mc = e.target.value; localStorage.setItem("fis.gal.mc", mc); update(null, "data"); } },
      el("option", { value: "", text: t("auto") }), ...(data.active.masscodes.length ? data.active.masscodes : [0, 1, 2, 3, 4, 5, 6, 7]).map(m =>
        el("option", { value: String(m), text: MC[m] + " · " + fmt(10 * (1 << m), 0) + " ly" })));
    mcSel.value = mc;
    side.append(frame(t("SURVEY SPHERE"), data.active.label, [
      el("div", { class: "gal-row" }, el("span", { class: "c-dim", text: t("Mass code") }), mcSel,
        el("span", { class: "c-dim", text: data.mc !== undefined ? MC[data.mc] : "" })),
      el("div", { class: "gal-boxbar" },
        el("i", { class: "closed", style: { flex: String(n.closed || 0.0001) } }), el("i", { class: "open", style: { flex: String(n.open || 0.0001) } }),
        el("i", { class: "unchecked", style: { flex: String(n.unchecked || 0.0001) } })),
      el("div", { class: "gal-legend" },
        el("span", { class: "c-green", text: "■ " + t("closed") + " " + n.closed }), el("span", { class: "c-amber", text: "■ " + t("open") + " " + n.open }),
        el("span", { class: "c-dim", text: "□ " + t("never checked") + " " + n.unchecked })),
      el("div", { class: "row-btns" },
        el("button", { text: t("sphere"), onclick: () => refit("sphere") }),
        el("button", { text: t("me"), onclick: () => refit("you") }),
        el("button", { text: t("all"), onclick: () => refit() })),
    ], { appear: false }));
  }
  side.append(el("div", { class: "legend" },
    el("span", { class: "c-violet", text: "■ " + t("only known to us") }), el("span", { class: "c-green", text: "■ " + t("visited") }),
    el("span", { class: "c-amber", text: "┄ " + t("carrier") }),
    ...Object.entries(FIND_COL).map(([k, c]) => el("span", { style: { color: c }, text: "◆ " + t(FIND_NAME[k]) })),
    el("span", { class: "c-dim", text: view3d()
      ? t("path: violet = old, cyan = recent · drag turns · right drag or two fingers pan · wheel zooms")
      : t("path: violet = old, cyan = recent · wheel zoom · drag · double click fits") })));
}
