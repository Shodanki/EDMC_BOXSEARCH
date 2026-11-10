// ATLAS – everything found, of one kind, nearest first.
// Tabs: ring hotspots · body signals · materials picked up · finds on the
// ground. Second picker narrows to one kind, the search box filters system,
// body and name. Click a row: datasheet of the body (PLANET); rows without a
// known body open the system in a new tab. The small map is a top view of the
// hits around you (galactic x/z, ly).

import { getJSON } from "../api.js";
import { el, frame, fmt } from "../ui.js";
import { t, N_ } from "../i18n.js";

const TABS = [["rings", N_("RINGS")], ["signals", N_("SIGNALS")], ["materials", N_("MATERIALS")], ["finds", N_("FINDS")],
  ["bio", N_("BIOLOGY")]];
// M1: bodies with bio signals from all your journals - open first by default
const BIO_KIND = { open: N_("still open"), done: N_("all analysed") };
const FIND_KIND = { codex: N_("codex finds"), bio_analyse: N_("biology analysed"),
  settlement: N_("settlements"), screenshot: N_("screenshots / waypoints") };
const FIND_SHORT = { codex: N_("codex"), bio_analyse: N_("bio ✔"), settlement: N_("settlement"), screenshot: N_("screenshot") };
const TONE = { rings: "#FFB23E", signals: "#3EF2E0", materials: "#B57CFF", finds: "#7CFF6B", bio: "#C6FF4D" };

let root = null, ctxRef = null, list = null, info = null, cv = null, pick = null, search = null, tabBar = null, range = null;
const RANGES = [25, 50, 100, 250, 500, 1000, 2000, 0];     // ly, 0 = everything
let state = { view: localStorage.getItem("fis.atlas.view") || "signals", kind: "", q: "",
  max: Number(localStorage.getItem("fis.atlas.max") || "0") };
let data = null, hover = -1, timer = null, dots = [];

export function mount(r, ctx) {
  root = r; ctxRef = ctx;
  root.classList.add("atlas-view");
  tabBar = el("div", { class: "at-tabs" });
  for (const [v, label] of TABS)
    tabBar.append(el("button", { "data-v": v, text: t(label), onclick: () => setView(v) }));
  pick = el("select", { class: "at-pick", onchange: () => { state.kind = pick.value; saveKind(); load(); } });
  range = el("select", { class: "at-pick at-range", title: t("only finds within this distance"),
    onchange: () => { state.max = Number(range.value); localStorage.setItem("fis.atlas.max", String(state.max)); load(); } },
    ...RANGES.map(r => el("option", { value: String(r), text: r ? "≤ " + fmt(r, 0) + " ly" : t("any distance") })));
  range.value = String(RANGES.includes(state.max) ? state.max : 0);
  search = el("input", { class: "at-search", type: "search", placeholder: t("search system, body, name …"),
    oninput: () => { clearTimeout(timer); timer = setTimeout(() => { state.q = search.value.trim(); load(); }, 250); } });
  info = el("div", { class: "at-info c-dim" });
  list = el("div", { class: "at-list scroll" });
  cv = el("canvas", { class: "at-map" });
  cv.addEventListener("mousemove", onMapMove);
  cv.addEventListener("mouseleave", () => { setHover(-1); });
  cv.addEventListener("click", () => { if (hover >= 0 && data) open(data.items[hover]); });
  new ResizeObserver(() => drawMap()).observe(cv);
  root.append(el("div", { class: "at-grid" },
    frame("ATLAS", "", [tabBar, el("div", { class: "at-bar" }, pick, range, search), info, list], { cls: "at-main" }),
    frame(t("AROUND YOU"), t("top view · ly"), cv, { cls: "at-side" })));
}

export function update(ctx, reason) {
  if (!root) return;
  if (reason === "show") setView(state.view, true);
}

function saveKind() { localStorage.setItem("fis.atlas.kind." + state.view, state.kind); }

async function setView(v, keepQuery) {
  state.view = v;
  localStorage.setItem("fis.atlas.view", v);
  for (const b of tabBar.querySelectorAll("button")) b.setAttribute("aria-pressed", b.dataset.v === v ? "true" : "false");
  const savedKind = localStorage.getItem("fis.atlas.kind." + v);
  state.kind = savedKind !== null ? savedKind : (v === "bio" ? "open" : "");
  if (!keepQuery) { state.q = ""; search.value = ""; }
  let kinds = [];
  try { kinds = (await getJSON("/api/atlas/kinds?view=" + v)).kinds || []; } catch (e) { kinds = []; }
  pick.replaceChildren(el("option", { value: "", text: t("(all)") }),
    ...kinds.map(k => el("option", { value: k.key,
      text: (v === "finds" && FIND_KIND[k.key] ? t(FIND_KIND[k.key]) : v === "bio" && BIO_KIND[k.key] ? t(BIO_KIND[k.key]) : k.label) + " (" + k.count + ")" })));
  if (![...pick.options].some(o => o.value === state.kind)) state.kind = "";
  pick.value = state.kind;
  load();
}

async function load() {
  const qs = new URLSearchParams({ view: state.view, limit: "120" });
  if (state.kind) qs.set("kind", state.kind);
  if (state.q) qs.set("q", state.q);
  if (state.max) qs.set("max", String(state.max));
  try { data = await getJSON("/api/atlas?" + qs.toString()); } catch (e) { data = null; }
  render();
}

function where(it) {
  if (state.view === "finds") {
    // which kind of find, when the list shows all of them
    const kind = state.kind ? "" : t(FIND_SHORT[it.key] || it.key) + " · ";
    return kind + (it.lat !== null && it.lat !== undefined ? fmt(it.lat, 4) + " / " + fmt(it.lon, 4) : t("no position"));
  }
  if (state.view === "rings") return it.ring_class || "";
  if (state.view === "bio") {
    const parts = [];
    if (it.missing && it.missing.length) parts.push(t("to find: {g}", { g: it.missing.join(", ") }));
    if (it.species && it.species.length) parts.push("✔ " + it.species.join(", "));
    if (it.codex_only && it.codex_only.length) parts.push(t("codex only: {g}", { g: it.codex_only.join(", ") }));
    return parts.join(" · ");
  }
  if (state.view === "materials") return it.category ? it.category + (it.last ? " · " + it.last : "") : (it.last || "");
  return "";
}

function render() {
  list.replaceChildren();
  hover = -1;
  if (!data || !data.items.length) {
    info.textContent = "";
    const hint = { rings: N_("Map a ring with the DSS – its hotspots land here."),
      signals: N_("Scan bodies with the FSS / DSS – their signals land here."),
      materials: N_("Pick up materials – where you were lands here."),
      finds: N_("Land, log codex entries, sample or take a screenshot – the places land here."),
      bio: N_("Scan bodies with the FSS / DSS – bodies with biological signals land here.") }[state.view];
    const why = state.q ? t("nothing matches “{q}”", { q: state.q })
      : state.max ? t("nothing within {n} ly – pick a larger distance", { n: fmt(state.max, 0) }) : t(hint);
    list.append(el("div", { class: "empty" }, why));
    drawMap(); return;
  }
  info.textContent = t("{n} of {total} · nearest first · click opens the datasheet", { n: data.items.length, total: data.total });
  if (data.totals) info.textContent += " · " + t("bio: {o} open signals on {b} bodies · {a} of {s} analysed",
    { o: data.totals.open, b: data.totals.bodies_open, a: data.totals.analysed, s: data.totals.signals });
  data.items.forEach((it, i) => {
    const row = el("div", { class: "at-row", "data-i": i, onclick: () => open(it),
      onmouseenter: () => setHover(i), onmouseleave: () => setHover(-1) },
      el("span", { class: "at-d", text: it.dist_ly !== null && it.dist_ly !== undefined ? fmt(it.dist_ly, 1) + " ly" : "–" }),
      el("span", { class: "at-sys", text: it.system }),
      el("span", { class: "at-body c-cyan", text: it.body_short || "" }),
      el("span", { class: "at-lab" + (state.view === "bio" ? (it.open ? " c-amber" : " c-green") : ""), text: state.view === "bio"
        ? (it.open ? t("{o} of {n} open", { o: it.open, n: it.signals }) : t("all {n} done", { n: it.signals }))
        : (it.label || "") + (it.count > 1 ? " ×" + it.count : "") }),
      el("span", { class: "at-w c-dim", text: where(it) }),
      el("button", { class: "at-copy", title: t("copy system name"), text: "⧉",
        onclick: (e) => { e.stopPropagation(); copy(it.system, e.target); } }));
    list.append(row);
  });
  drawMap();
}

function open(it) {
  if (!it) return;
  if (it.body_id !== undefined && it.body_id !== null) ctxRef.select(it.id64, it.body_id, true);
  else window.open("/?system=" + it.id64 + "#tactical", "_blank");
}

async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); btn.textContent = "✓"; }
  catch (e) { btn.textContent = "×"; }
  setTimeout(() => { btn.textContent = "⧉"; }, 1200);
}

function setHover(i) {
  if (i === hover) return;
  hover = i;
  for (const r of list.querySelectorAll(".at-row")) r.classList.toggle("hot", Number(r.dataset.i) === i);
  if (i >= 0) { const r = list.querySelector('.at-row[data-i="' + i + '"]'); if (r) r.scrollIntoView({ block: "nearest" }); }
  drawMap();
}

function onMapMove(e) {
  const rc = cv.getBoundingClientRect();
  const x = e.clientX - rc.left, y = e.clientY - rc.top;
  let best = -1, bd = 12 * 12;
  for (const d of dots) { const q = (d.x - x) ** 2 + (d.y - y) ** 2; if (q < bd) { bd = q; best = d.i; } }
  cv.style.cursor = best >= 0 ? "pointer" : "";
  setHover(best);
}

function drawMap() {
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = Math.max(1, W * dpr); cv.height = Math.max(1, H * dpr);
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  dots = [];
  if (W < 60 || H < 60) return;           // view hidden or too small
  const items = (data && data.items) || [];
  const pts = items.map((it, i) => ({ it, i })).filter(p => p.it.rel);
  const far = Math.max(10, ...pts.map(p => Math.hypot(p.it.rel[0], p.it.rel[2])));
  const maxd = state.max ? state.max : far;
  const R = Math.min(W, H) / 2 - 16, cx = W / 2, cy = H / 2;
  // linear within a chosen range; square-root for "any distance" (near finds
  // keep room, the far ones still fit)
  const sq = !state.max && far > 250;
  const scale = (d) => R * (sq ? Math.sqrt(d / maxd) : d / maxd);
  g.strokeStyle = "rgba(62,242,224,.14)"; g.fillStyle = "#6E8F8B"; g.font = "10px monospace";
  const rings = sq ? [25, 100, 250, 500, 1000, 2000, 5000, 10000, 20000].filter(r => r <= maxd * 1.05)
    : (() => { const st = maxd > 400 ? 200 : maxd > 150 ? 50 : maxd > 60 ? 25 : 10; const a = []; for (let r = st; r <= maxd * 1.05; r += st) a.push(r); return a; })();
  for (const r of rings) {
    const rr = scale(r);
    g.beginPath(); g.arc(cx, cy, rr, 0, Math.PI * 2); g.stroke();
    g.fillText(fmt(r, 0) + " ly", cx + rr * 0.71 + 3, cy - rr * 0.71 - 3);
  }
  g.beginPath(); g.moveTo(cx - 6, cy); g.lineTo(cx + 6, cy); g.moveTo(cx, cy - 6); g.lineTo(cx, cy + 6);
  g.strokeStyle = "#CFEDEA"; g.stroke();
  // hits: galactic x to the right, z up (towards the core)
  const col = TONE[state.view] || "#3EF2E0";
  for (const p of pts) {
    const d = Math.hypot(p.it.rel[0], p.it.rel[2]) || 1e-9;
    const k = Math.min(scale(d), R + 4) / d;
    const x = cx + p.it.rel[0] * k, y = cy - p.it.rel[2] * k;
    dots.push({ x, y, i: p.i });
    const hot = p.i === hover;
    g.fillStyle = hot ? "#FFFFFF" : col;
    g.globalAlpha = hot ? 1 : 0.75;
    g.beginPath(); g.arc(x, y, hot ? 5 : 3, 0, Math.PI * 2); g.fill();
    if (hot) { g.font = "11px monospace"; g.fillText(p.it.system + (p.it.body_short ? " " + p.it.body_short : ""), x + 8, y - 6); }
  }
  g.globalAlpha = 1;
  g.fillStyle = "#6E8F8B"; g.font = "10px monospace";
  g.fillText(t("you") + " +   " + t("core") + " ↑" + (sq ? "   " + t("√ scale") : ""), 8, H - 8);
}
