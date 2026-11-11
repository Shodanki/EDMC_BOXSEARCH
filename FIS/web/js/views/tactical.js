// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// SYSTEM – the current system in 3D (view id "tactical").
// Three.js if the CDN is reachable, otherwise the 2D canvas fallback.

import { el, frame, fmt, chip, ago, classDe, fixLabel } from "../ui.js";
import { t, N_ } from "../i18n.js";

// SYSTEM REPORT: the server sends facts (fis/science.system_report), the words are here
const SYS_SECTION = { class: N_("Classification"), record: N_("Record"), biology: N_("Biology"), geology: N_("Geology"),
  resources: N_("Resources"), notable: N_("Notable"), hazards: N_("Hazards"), advice: N_("Recommendation") };
const SYS_REPORT = {
  sys_bodies: N_("{stars} star(s) of class {types} and {planets} planets and moons in the database ({known} bodies in the system)."),
  sys_fss_done: N_("FSS complete - every body found."),
  sys_fss_open: N_("FSS not complete - there is more to find."),
  sys_first: N_("{n} bodies discovered first by you."),
  sys_valuable: N_("Valuable: {list}."),
  sys_bio: N_("{n} biological signals on {p} planets, {done} analysed."),
  sys_geo: N_("{n} geological signals on {p} bodies."),
  sys_rings: N_("{n} ringed planets: {list}."),
  sys_jumponium: N_("Every premium FSD injection material on: {list}."),
  sys_eccentric: N_("Highly eccentric orbits: {list}."),
  sys_fast_orbit: N_("Around their parent in under 6 hours: {list}."),
  sys_fast_spin: N_("Days shorter than an hour: {list}."),
  sys_close: N_("Moons close above their planet: {list}."),
  sys_many_moons: N_("Many moons: {list}."),
  sys_nested: N_("Moons of moons: {list}."),
  sys_landable_atmo: N_("Landable with an atmosphere: {list}."),
  sys_far: N_("Far out (over 100,000 LS): {list}."),
  sys_neutron: N_("Neutron star {name}: its jet cones damage the FSD - and supercharge it (range ×4)."),
  sys_white_dwarf: N_("White dwarf {name}: its jet cones supercharge the FSD (range ×1.5), at a cost to the FSD."),
  sys_black_hole: N_("Black hole {name}: mind the lensing on approach."),
  sys_heavy: N_("Heavy landings: {list}."),
  sys_next_fss: N_("Next: finish the FSS."),
  sys_next_dss: N_("Next: map {n} with the DSS ({list})."),
  sys_next_bio: N_("Next: {n} biological signals still to analyse."),
  sys_next_done: N_("Nothing left to do here - jump on."),
};
const SYS_LEVEL = { good: "c-green", warn: "c-amber", danger: "c-red", info: "" };
import { buildScene, drawOverlay, groupBounds, pick } from "./scene.js";
import { create2D } from "./render2d.js";

let root, stage, overlay, side, ctxRef;
let renderer = null;
let scene = null;
let screen = new Map();
let hover = null;
let lastSysId = null, lastNext = null;
const prefs = {
  mode: localStorage.getItem("fis.tac.mode") || "log",
  autofocus: localStorage.getItem("fis.tac.autofocus") !== "0",
};

export function mount(r, ctx) {
  root = r; ctxRef = ctx;
  root.classList.add("tac-view");
  stage = el("div", { class: "tac-stage" });
  overlay = el("canvas", { class: "tac-overlay" });
  stage.append(overlay);
  side = el("aside", { class: "tac-side" });
  const bar = el("div", { class: "tac-bar" },
    el("button", { id: "tac-mode", onclick: toggleMode, title: t("Distance scale") }),
    el("button", { id: "tac-auto", onclick: toggleAuto, title: t("Focus the planet group of the next stop automatically") }),
    el("button", { onclick: () => renderer && renderer.overview(false), text: t("Overview") }),
    el("span", { id: "tac-engine", class: "c-dim" }),
    el("span", { id: "tac-fix", class: "tac-fix" }));
  root.append(el("div", { class: "tac-main" }, bar, stage), side);
  syncButtons();
  initRenderer();
  stage.addEventListener("pointermove", onMove);
  stage.addEventListener("click", onClick);
  stage.addEventListener("dblclick", onDbl);
  new ResizeObserver(sizeOverlay).observe(stage);
  sizeOverlay();
}

async function initRenderer() {
  const eng = () => document.getElementById("tac-engine");
  try {
    // ?2d forces the canvas view (weak tablets, or to test the fallback)
    if (new URLSearchParams(location.search).has("2d")) throw new Error("2d requested");
    const mod = await Promise.race([
      import("./render3d.js"),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 8000)),
    ]);
    renderer = mod.create3D(stage);
    eng().textContent = "3D · Three.js";
  } catch (err) {
    renderer = create2D(stage);
    eng().textContent = err.message === "2d requested" ? t("2D · chosen with ?2d") : t("2D · offline (Three.js not reachable)");
    eng().className = "c-amber";
  }
  renderer.onFrame = redrawOverlay;
  if (scene) renderer.setScene(scene, false);
  focusNext(true);
}

function sizeOverlay() {
  const dpr = window.devicePixelRatio || 1;
  overlay.width = Math.max(1, stage.clientWidth * dpr);
  overlay.height = Math.max(1, stage.clientHeight * dpr);
  overlay.style.width = stage.clientWidth + "px";
  overlay.style.height = stage.clientHeight + "px";
  redrawOverlay();
}

function redrawOverlay() {
  if (!renderer || !scene) { overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height); return; }
  const sel = ctxRef.store.selected;
  screen = drawOverlay(overlay.getContext("2d"), overlay.width, overlay.height, scene, renderer.project, {
    selected: sel && scene && ctxRef.store.system && sel.id64 === ctxRef.store.system.id64 ? sel.body_id : null,
    hover: hover,
    radius: (b) => renderer.radiusPx(b.size, b.p),
  });
}

function syncButtons() {
  const m = document.getElementById("tac-mode");
  if (m) m.textContent = prefs.mode === "log" ? t("Scale: LOG") : t("Scale: LINEAR");
  const a = document.getElementById("tac-auto");
  if (a) { a.textContent = t("Auto focus"); a.setAttribute("aria-pressed", prefs.autofocus ? "true" : "false"); }
}
function toggleMode() {
  prefs.mode = prefs.mode === "log" ? "lin" : "log";
  localStorage.setItem("fis.tac.mode", prefs.mode);
  syncButtons(); rebuild(false);
}
function toggleAuto() {
  prefs.autofocus = !prefs.autofocus;
  localStorage.setItem("fis.tac.autofocus", prefs.autofocus ? "1" : "0");
  syncButtons();
  if (prefs.autofocus) focusNext(true);
}

function rebuild(keepView) {
  const sys = ctxRef.store.system;
  scene = sys && sys.bodies && sys.bodies.length ? buildScene(sys, prefs.mode) : null;
  if (scene) { scene.carrier = sys.carrier || null; scene.carrierIn = sys.carrier_incoming || null; }
  if (renderer) {
    if (scene) renderer.setScene(scene, keepView);
    else renderer.setScene({ bodies: [], route: [], rings: [], extent: 10, byId: new Map() }, false);
  }
  redrawOverlay();
}

function focusGroupOf(bodyId) {
  if (!scene || !renderer) return;
  const b = scene.byId.get(bodyId);
  if (!b) return;
  const g = groupBounds(scene, b.group);
  if (g) renderer.focus(g.c, g.r);
}

function focusNext(force) {
  const sys = ctxRef.store.system;
  if (!prefs.autofocus || !sys || !sys.route || !renderer || !scene) return;
  const nx = sys.route.next;
  if (!force && nx === lastNext) return;
  lastNext = nx;
  const leg = nx ? sys.route.legs[nx - 1] : null;
  if (leg) focusGroupOf(leg.body_id);
}

// ------------------------------------------------------------ interaction
function localXY(e) { const r = stage.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function onMove(e) {
  if (!scene) return;
  const [x, y] = localXY(e);
  const b = pick(screen, scene, x, y);
  const id = b ? b.id : null;
  stage.style.cursor = b ? "pointer" : "";
  if (id !== hover) { hover = id; redrawOverlay(); }
}
function onClick(e) {
  if (!scene || (renderer && renderer.dragged)) return;
  const [x, y] = localXY(e);
  const b = pick(screen, scene, x, y);
  if (b) ctxRef.select(ctxRef.store.system.id64, b.id, false);
}
function onDbl(e) {
  if (!scene) return;
  const [x, y] = localXY(e);
  const b = pick(screen, scene, x, y);
  if (b) focusGroupOf(b.id);
}

// ------------------------------------------------------------- side panel
const RING_CLS = { Icy: N_("icy"), Rocky: N_("rocky"), Metalic: N_("metallic"), MetalRich: N_("metal-rich") };
function ringClass(c) {
  const k = String(c || "").replace("eRingClass_", "").replace(/[$;]/g, "");
  return RING_CLS[k] ? t(RING_CLS[k]) : (k || "?");
}

function systemReport(sys) {
  if (!sys.report || !sys.report.length) return null;
  const rows = [];
  let last = null;
  for (const f of sys.report) {
    if (f.section !== last) { rows.push(el("div", { class: "sr-h", text: t(SYS_SECTION[f.section] || f.section) })); last = f.section; }
    const v = {};
    for (const [k, x] of Object.entries(f.v || {})) v[k] = typeof x === "number" ? fmt(x, 0) : (x ?? "–");
    rows.push(el("div", { class: "sr-line " + (SYS_LEVEL[f.level] || "") }, t(SYS_REPORT[f.id] || f.id, v)));
  }
  rows.push(el("div", { class: "c-dim small", text: t("Rule-based from the journal and the plugin database – no AI.") }));
  return frame(t("SYSTEM REPORT"), "", rows, { cls: "sr-frame", appear: false });
}

// M10: points of interest - stations, settlements, carriers, beacons
const POI_ICON = { station: "▣", settlement: "⌂", carrier: "◈", extraction: "⛏", beacon: "◎" };
const POI_KIND = { station: N_("station"), settlement: N_("settlement"), carrier: N_("fleet carrier"),
  extraction: N_("extraction site"), beacon: N_("nav beacon") };
function poiFrame(sys) {
  const list = sys.poi || [];
  if (!list.length) return null;
  const CARRIERS_SHOWN = 8;                // the latest sightings; the bubble has dozens
  const nCar = list.filter(p => p.kind === "carrier").length;
  let car = 0;
  const shown = list.filter(p => p.kind !== "carrier" || car++ < CARRIERS_SHOWN);
  const rows = shown.map(p => {
    const bits = [t(POI_KIND[p.kind] || p.kind)];
    if (p.body) bits.push(p.body);
    if (p.dist_ls !== undefined && p.dist_ls !== null) bits.push(fmt(p.dist_ls, 0) + " LS");
    if (p.docked) bits.push(t("docked"));
    if (p.seen) bits.push(t("seen {d}", { d: String(p.seen).slice(0, 10) }));
    return el("div", { class: "sr-line" },
      p.favourite ? el("span", { class: "poi-fav", title: t("favourite"), text: "★ " }) : null,
      el("span", { class: "c-cyan", text: (POI_ICON[p.kind] || "·") + " " + p.name }),
      el("span", { class: "c-dim small", text: "  " + bits.join(" · ") }));
  });
  if (nCar > CARRIERS_SHOWN) rows.push(el("div", { class: "c-dim small", text: t("+{n} more fleet carriers seen here", { n: nCar - CARRIERS_SHOWN }) }));
  rows.push(el("div", { class: "c-dim small", text: t("From your own journals - carriers move on.") }));
  return frame(t("POINTS OF INTEREST"), String(list.length), rows, { cls: "sr-frame", appear: false });
}

// another system pinned (?system=, from ATLAS, GALAXY, MINING): one click
// back to the live system you are in - the rest of the address stays
function backToCurrent() {
  const q = new URLSearchParams(location.search);
  if (!/^\d+$/.test(q.get("system") || "")) return null;
  return el("button", { class: "sys-back", text: "⟲ " + t("back to the current system"),
    title: t("show the system you are in, live"),
    onclick: () => { q.delete("system"); const s = q.toString(); location.href = location.pathname + (s ? "?" + s : "") + "#tactical"; } });
}

function renderSide() {
  const sys = ctxRef.store.system;
  side.replaceChildren();
  if (!sys) {
    side.append(frame("SYSTEM", "", el("div", { class: "empty", text: t("No system known yet – reading the journal …") })));
    return;
  }
  const head = [
    el("div", { class: "tac-sys" }, sys.name || "?"),
    el("div", { class: "c-dim" }, (sys.star_class ? t("Star") + " " + sys.star_class + " · " : "") +
      t("{n} bodies", { n: sys.body_count ? sys.bodies.length + "/" + sys.body_count : sys.bodies.length }) +
      (sys.fss_complete ? " · " + t("FSS complete") : "")),
  ];
  if (sys.carrier) {
    const c = sys.carrier, at = c.body_id !== null && c.body_id !== undefined && sys.bodies.find((b) => b.body_id === c.body_id);
    head.push(el("div", { class: "c-amber", text: (c.expected ? t("Your carrier {n} should be here", { n: c.name || "" })
      : t("Your carrier {n} is here", { n: c.name || "" })) + (at ? " · " + (at.short || at.name) : "") }));
  }
  if (sys.carrier_incoming) {
    const c = sys.carrier_incoming;
    head.push(el("div", { class: "c-amber", text: t("Your carrier {n} jumps here · {t}", { n: c.name || "",
      t: c.departure ? new Date(c.departure * 1000).toLocaleString() : "?" }) }));
  }
  // I1: "in no database" only where a source was really asked
  const lvl = sys.info_level;
  const noDb = !sys.known_sources.length && (!lvl || lvl === "checked");
  if (sys.known_sources.length) head.push(el("div", { class: "c-dim", text: t("known: {s}", { s: sys.known_sources.join(", ") }) }));
  else if (lvl === "inhabited") head.push(el("div", { class: "c-dim", text: t("inhabited – known to the databases") }));
  else if (lvl === "unchecked") head.push(el("div", { class: "c-dim", text: t("not checked – outside our data frame") }));
  else head.push(el("div", {}, chip(t("in no database"), "first")));
  const back = backToCurrent();
  if (back) side.append(back);
  side.append(frame("SYSTEM", sys.visited ? t("visited") : "", head, { kind: noDb ? "disc" : "", appear: false }));

  side.append(systemReport(sys));
  const poi = poiFrame(sys);
  if (poi) side.append(poi);

  // flight plan
  const r = sys.route;
  if (r && r.legs.length) {
    const list = el("ol", { class: "legs" });
    for (const l of r.legs) {
      const cls = ["leg", l.done ? "done" : "", r.next === l.n ? "next" : "", l.group_start && l.n > 1 ? "gs" : "",
        ctxRef.store.selected && ctxRef.store.selected.body_id === l.body_id ? "sel" : ""].join(" ");
      list.append(el("li", { class: cls, onclick: () => { ctxRef.select(sys.id64, l.body_id, false); focusGroupOf(l.body_id); },
                              ondblclick: () => ctxRef.select(sys.id64, l.body_id, true) },
        el("span", { class: "lg-n", text: String(l.n).padStart(2, "0") }),
        el("span", { class: "lg-name", text: (l.moon ? "  " : "") + l.short }),
        el("span", { class: "lg-ls", text: fmt(l.leg_ls, 0) + " LS" }),
        el("span", { class: "lg-min", text: "~" + fmt(Math.max(1, l.leg_min), 0) + "′" }),
        el("div", { class: "lg-work", text: l.work || "" })));
    }
    const tag = (r.full_tour ? t("all done · full tour") + " · " : "") + fmt(r.total_ls, 0) + " LS · ~" + fmt(r.total_min, 0) + " min"
      + " · " + (r.calibrated ? t("times: journal") : t("times: default"));
    side.append(frame(t("FLIGHT PLAN"), tag, el("div", { class: "scroll legs-box" }, list), { appear: false }));
  } else if (sys.bodies && sys.bodies.length) {
    // never just gone: say why there is nothing to fly to
    side.append(frame(t("FLIGHT PLAN"), (r && r.filters ? r.filters.join(", ") : ""),
      el("div", { class: "c-dim small", text: t("No stop under the route filter – nothing left to do here, or only stars known so far (FSS).") }),
      { appear: false }));
  }

  // biology of the system: what is done, being sampled, still to find
  if (sys.bio && sys.bio.length) {
    const box = el("div", { class: "scroll bio-box" });
    let nDone = 0, nOpen = 0;
    for (const b of sys.bio) {
      const rows = [];
      // M1: what is still to do comes first; analysed species fold into one
      // line (names on hover) so finished work does not crowd the list
      const done = b.species.filter(s => s.state === "done");
      for (const s of b.species) {
        if (s.state === "done") { nDone++; continue; }
        nOpen++;
        rows.push(el("div", { class: "bio-sp c-amber", text: "◐ " + s.samples + "/3 " + s.species }));
      }
      for (const g of b.missing) { nOpen++; rows.push(el("div", { class: "bio-sp c-violet", text: "? " + t("{g} – not found yet", { g }) })); }
      if (done.length) rows.push(el("div", { class: "bio-sp c-green" + (rows.length ? " small" : ""), title: done.map(s => s.species).join(", "),
        text: "✔ " + (done.length === 1 ? done[0].species : t("{n} analysed", { n: done.length })) }));
      if (!b.species.length && !b.missing.length)
        rows.push(el("div", { class: "bio-sp c-dim", text: b.hint || t("FSS count only – the DSS names the genera") }));
      const finished = done.length && done.length === b.species.length && !b.missing.length && done.length >= b.signals;
      box.append(el("div", { class: "bio-body" + (finished ? " bio-done" : ""), onclick: () => { ctxRef.select(sys.id64, b.body_id, false); focusGroupOf(b.body_id); } },
        el("div", { class: "bio-h" }, el("span", { class: "c-cyan", text: b.short }),
          el("span", { class: "c-dim", text: "  Bio ×" + b.signals + " · " + fmt(b.arrival_ls, 0) + " LS" })),
        ...rows));
    }
    side.append(frame("BIO", t("{d} analysed · {o} open", { d: nDone, o: nOpen }), box, { appear: false }));
  }

  // selection
  const sel = ctxRef.store.selected;
  const b = sel && sys.bodies.find((x) => x.body_id === sel.body_id);
  if (b) {
    const chips = [];
    if (b.flags.first) chips.push(chip(t("first discovery"), "first"));
    if (b.flags.bio) chips.push(chip("Bio ×" + b.flags.bio + (b.flags.organics ? " (" + b.flags.organics + " ✓)" : ""), "bio"));
    if (b.flags.geo) chips.push(chip("Geo ×" + b.flags.geo, "geo"));
    if (b.flags.mapped) chips.push(chip(t("mapped"), "mapped"));
    if (b.flags.footfall) chips.push(chip(t("first footfall"), "ff"));
    if (b.flags.valuable) chips.push(chip(t("valuable"), "val"));
    side.append(frame(t("SELECTION"), b.kind === "Star" ? t("Star") : (b.moon ? t("Moon") : t("Planet")), [
      el("div", { class: "tac-sys" }, b.short),
      el("div", { class: "c-dim", text: (b.kind === "Star" ? t("Star") + " " + b.cls : classDe(b.cls)) + " · " + fmt(b.arrival_ls, 0) + " LS" + (b.landable ? " · " + t("landable") : "") }),
      el("div", {}, ...chips),
      b.bio_hint ? el("div", { class: "c-amber", text: b.bio_hint }) : null,
      ...(b.rings || []).filter((r) => !r.belt).map((r) => el("div", { class: "small" },
        el("span", { class: "c-cyan", text: (r.name || "").replace(sys.name || "", "").trim() }),
        el("span", { class: "c-dim", text: " · " + ringClass(r.cls) + (r.inner_km && r.outer_km ? " · " + fmt(r.inner_km, 0) + "–" + fmt(r.outer_km, 0) + " km" : "") }),
        r.hotspots && r.hotspots.length ? el("span", { class: "c-amber", text: " · ◎ " + r.hotspots.map((h) => h.material + (h.count > 1 ? " ×" + h.count : "")).join(", ") }) : null)),
      el("button", { onclick: () => ctxRef.show("planet"), text: t("Datasheet") + " ⟶" }),
    ], { kind: "hot", appear: false }));
  }

  side.append(el("div", { class: "legend" },
    el("span", { class: "c-violet", text: "○ " + t("first discovery") }), el("span", { class: "c-amber", text: "◌ Bio" }),
    el("span", { class: "c-green", text: "✓ " + t("mapped") }), el("span", { class: "c-violet", text: "FF " + t("first footfall") }),
    el("span", { class: "c-dim", text: t("Sizes not to scale · positions from Kepler orbits") })));
}

export function update(ctx, reason) {
  if (!root) return;
  const sys = ctx.store.system;
  const fixEl = document.getElementById("tac-fix");
  if (fixEl) {
    fixEl.textContent = sys && sys.fix ? fixLabel(sys.fix) : "";
    fixEl.title = t("Last reference point from the journal – not an exact ship position");
  }
  if (reason === "data" || reason === "show") {
    const newSys = sys ? sys.id64 : null;
    const changed = newSys !== lastSysId;
    lastSysId = newSys;
    if (reason === "data" || !scene) rebuild(!changed);
    if (changed) { lastNext = null; if (renderer && scene) renderer.overview(true); }
    focusNext(changed);
  }
  if (reason === "show" && renderer) { renderer.resize(); sizeOverlay(); }
  renderSide();
  redrawOverlay();
  if (renderer) renderer.redraw();
}

// read-only debugging handle (browser console): window.__fisTac.scene / .renderer
window.__fisTac = { get scene() { return scene; }, get renderer() { return renderer; } };
