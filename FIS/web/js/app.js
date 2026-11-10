// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// SHBOX FIS – application shell: state, view switching, ship bar, live push.

import { getJSON, subscribe } from "./api.js";
import { fmt } from "./ui.js";
import { initLang, t, N_, lang, setLang, locale, applyStatic } from "./i18n.js";
import * as layout from "./layout.js";
import * as fullscreen from "./fullscreen.js";
import * as briefing from "./views/briefing.js";
import * as tactical from "./views/tactical.js";
import * as planet from "./views/planet.js";
import * as surface from "./views/surface.js";
import * as atlas from "./views/atlas.js";
import * as ship from "./views/ship.js";
import * as carrier from "./views/carrier.js";
import * as galaxy from "./views/galaxy.js";
import * as statistics from "./views/statistics.js";
import * as mining from "./views/mining.js";
import * as settings from "./views/settings.js";

const VIEWS = { briefing, tactical, planet, surface, atlas, ship, carrier, galaxy, statistics, mining, settings };
// ?solo=ship: one view alone in its own window (second screen, tablet)
// ?system=<id64> pins another system (detail window from GALAXY, review)
const PINNED = (/^\d+$/.exec(new URLSearchParams(location.search).get("system") || "") || [null])[0];
const SOLO = (() => { const v = new URLSearchParams(location.search).get("solo"); return v && VIEWS[v] ? v : null; })();
if (SOLO) document.body.classList.add("solo");
// E6/P7 display profile - links made on the settings page, never typed:
// obs=1 transparent background for an OBS browser source, kiosk=1 without
// the solo control, scale=0.75..2 text and frame size
const PROFILE = (() => {
  const q = new URLSearchParams(location.search);
  const sc = Number(q.get("scale"));
  return { obs: q.get("obs") === "1", kiosk: q.get("kiosk") === "1" || q.get("obs") === "1",
    scale: sc >= 0.5 && sc <= 3 ? sc : null };
})();
if (PROFILE.obs) document.body.classList.add("obs");
// M12: the FIS as an installed app (own window, taskbar icon) - only on the
// game PC: browsers allow it on localhost, not on plain http in the home
// network. No service worker: nothing is cached, an update is live at once.
const ON_THIS_PC = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
if (ON_THIS_PC && !SOLO && !PROFILE.obs) {
  const link = document.createElement("link");
  link.rel = "manifest"; link.href = "/manifest.webmanifest";
  link.crossOrigin = "use-credentials";        // LAN mode: the token cookie goes along
  document.head.append(link);
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); window.fisInstall = e; });
  window.addEventListener("appinstalled", () => { window.fisInstall = null; });
}
if (PROFILE.kiosk) document.body.classList.add("kiosk");
if (PROFILE.scale) document.documentElement.style.zoom = String(PROFILE.scale);

// language first: every view renders its texts through t()
await initLang();
applyStatic();
for (const b of document.querySelectorAll("#lang button")) {
  b.setAttribute("aria-pressed", b.dataset.lang === lang() ? "true" : "false");
  b.addEventListener("click", () => setLang(b.dataset.lang));
}
const FOOT = N_("Reads game files only · no input to the game · no AI at runtime");

// screen size -> layout (desktop / tablet / phone), choosable in the footer
// and - with no footer in a solo window - in a small control at the top right
layout.apply();
document.querySelector("#foot .foot-opts").prepend(layout.picker("lay-pick"));
document.getElementById("shipbar").append(fullscreen.button());
if (SOLO) {
  const ctl = document.createElement("div");
  ctl.id = "solo-ctl";
  const langs = document.createElement("span");
  langs.className = "lang";
  for (const l of ["en", "de"]) {
    const b = document.createElement("button");
    b.textContent = l.toUpperCase();
    b.setAttribute("aria-pressed", l === lang() ? "true" : "false");
    b.addEventListener("click", () => setLang(l));
    langs.append(b);
  }
  const full = document.createElement("a");
  full.href = location.pathname + "#" + SOLO;
  full.textContent = "FIS";
  full.title = t("all views");
  if (PINNED) {
    const tag = document.createElement("span");
    tag.className = "solo-detail";
    tag.textContent = t("DETAIL VIEW");
    tag.title = t("this window shows one system - live data stays in the main window");
    ctl.append(tag);
  }
  ctl.append(fullscreen.button(), layout.picker("lay-pick"), langs, full);
  document.body.append(ctl);
}
// home network: show where other devices find the page (never the token)
getJSON("/api/config").then((c) => {
  if (!c || !c.lan || !c.lan_urls || !c.lan_urls.length) return;
  const f = document.getElementById("foot-lan");
  f.textContent = t("Home network: {u}", { u: c.lan_urls[0] });
  f.title = c.lan_urls.join(" · ");
}).catch(() => {});

const store = {
  live: null, system: null, briefing: null, ship: null,
  selected: null,           // { id64, body_id }
  view: null,
  connected: false,
};

const ctx = {
  store,
  select(id64, bodyId, open = false) {
    store.selected = { id64, body_id: bodyId };
    planet.load(ctx);
    if (open) show("planet");
    else tactical.update(ctx, "select");
  },
  show: (v) => show(v),
  refresh: (what) => refresh(what),
};

// ------------------------------------------------------------- settings
const OPTS = { scan: "fis.scanlines", motion: "fis.motion", autoview: "fis.autoview" };
function loadOpt(k, def) { const v = localStorage.getItem(OPTS[k]); return v === null ? def : v === "1"; }
function applyOpts() {
  // OBS: never scanlines or vignette over the stream picture
  document.body.classList.toggle("scanlines", !PROFILE.obs && document.getElementById("opt-scan").checked);
  document.body.classList.toggle("motion", document.getElementById("opt-motion").checked);
}
for (const [k, id] of [["scan", "opt-scan"], ["motion", "opt-motion"], ["autoview", "opt-autoview"]]) {
  const box = document.getElementById(id);
  box.checked = loadOpt(k, true);
  box.addEventListener("change", () => { localStorage.setItem(OPTS[k], box.checked ? "1" : "0"); applyOpts(); });
}
applyOpts();
const autoView = () => document.getElementById("opt-autoview").checked;

// ---------------------------------------------------------------- views
const mounted = new Set();
function show(name) {
  if (!VIEWS[name]) name = "tactical";
  store.view = name;
  for (const sec of document.querySelectorAll(".view")) sec.hidden = sec.dataset.view !== name;
  for (const b of document.querySelectorAll("#tabs button"))
    b.setAttribute("aria-selected", b.dataset.view === name ? "true" : "false");
  const root = document.getElementById("view-" + name);
  if (!mounted.has(name)) { VIEWS[name].mount(root, ctx); mounted.add(name); }
  VIEWS[name].update(ctx, "show");
  if (location.hash !== "#" + name) history.replaceState(null, "", location.pathname + location.search + "#" + name);
}
for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => show(b.dataset.view));
// hand-edited URL hash / bookmarks (#briefing, #tactical, #planet)
// the names on the tabs work as addresses too (#system, #planetinfo)
const ALIAS = { system: "tactical", planetinfo: "planet", stats: "statistics" };
window.addEventListener("hashchange", () => {
  const name = ALIAS[location.hash.slice(1)] || location.hash.slice(1);
  if (!SOLO && VIEWS[name] && name !== store.view) show(name);
});
window.addEventListener("keydown", (e) => {
  if (e.target && e.target.matches && e.target.matches("input, textarea, select")) return;
  if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey && !e.altKey) { fullscreen.toggle(); return; }
  if (SOLO) return;
  // keys follow the tab order: briefing, planet, system, galaxy, planet info ...
  const map = { "1": "briefing", "2": "surface", "3": "tactical", "4": "galaxy", "5": "planet",
    "6": "atlas", "7": "ship", "8": "carrier", "9": "mining", "0": "statistics" };
  if (map[e.key]) show(map[e.key]);
});

// ------------------------------------------------------------ refreshing
const timers = {};
function later(key, ms, fn) {
  if (timers[key]) return;
  timers[key] = setTimeout(() => { timers[key] = null; fn(); }, ms);
}

async function refresh(what) {
  try {
    if (what === "system" || what === "all") {
      // ?system=<id64> pins another system (review, second screen)
      store.system = await getJSON(PINNED ? "/api/system/" + PINNED : "/api/system/current");
      if (PINNED && store.system && store.system.name) document.title = store.system.name + " · " + t("DETAIL VIEW") + " · SHBOX FIS";
      if (store.system && (!store.selected || store.selected.id64 !== store.system.id64)) {
        store.selected = null;
      }
      if (mounted.has("tactical")) tactical.update(ctx, "data");
    }
    if (what === "briefing" || what === "all") {
      store.briefing = await getJSON("/api/briefing");
      try { store.survey = await getJSON("/api/survey"); } catch (e) { store.survey = null; }
      if (mounted.has("briefing")) briefing.update(ctx, "data");
    }
    if (what === "ship" || what === "all") {
      store.ship = await getJSON("/api/ship");
      renderShipBar();
      if (mounted.has("briefing") && store.view === "briefing") briefing.update(ctx, "ship");
    }
    if ((what === "planet" || what === "all") && store.selected && mounted.has("planet")) {
      planet.load(ctx);
    }
  } catch (err) {
    setFoot(t("Loading failed: {e}", { e: err.message }), true);
  }
}

function setFoot(msg, bad = false) {
  const f = document.getElementById("foot-msg");
  f.textContent = msg;
  f.className = bad ? "c-red" : "";
  if (bad) later("foot", 6000, () => setFoot(t(FOOT)));
}

// --------------------------------------------------------------- ship bar
const FOCUS = { "NONE": N_("COCKPIT"), "GALAXY MAP": N_("GALAXY MAP"), "SYSTEM MAP": N_("SYSTEM MAP"),
  "INTERNAL": N_("INTERNAL"), "EXTERNAL": N_("EXTERNAL"), "COMMS": N_("COMMS"), "ROLE": N_("ROLE"),
  "STATION": "STATION", "ORRERY": "ORRERY", "FSS": "FSS", "SAA": "DSS", "CODEX": N_("CODEX") };

function renderShipBar() {
  const s = store.ship || {};
  const sys = s.system || {};
  document.getElementById("sb-system").textContent = sys.name || "–";
  const f = s.fuel || {};
  const bar = document.getElementById("sb-fuel-bar");
  const pct = f.pct ?? (f.capacity ? 100 * (f.main || 0) / f.capacity : null);
  bar.style.width = pct !== null && pct !== undefined ? Math.min(100, pct).toFixed(1) + "%" : "0";
  bar.parentElement.className = "bar" + (f.warning ? (f.jumps_left <= 2 ? " alert" : " warn") : "");
  let txt = f.main !== null && f.main !== undefined ? fmt(f.main, 1) + " t" : "–";
  if (f.jumps_left !== null && f.jumps_left !== undefined) txt += " · " + t("{n} jmp", { n: f.jumps_left });
  const fv = document.getElementById("sb-fuel");
  fv.textContent = txt;
  fv.title = f.summary || "";
  fv.className = "v " + (f.warning ? (f.jumps_left <= 2 ? "c-red" : "c-amber") : "c-green");
  const tgt = s.target;
  const tEl = document.getElementById("sb-target");
  if (s.jumping) tEl.textContent = "⟫ " + (s.jumping.name || t("Jump"));
  else tEl.textContent = tgt ? (tgt.name || "–") + (tgt.star_class ? " [" + tgt.star_class + "]" : "") : "–";
  const flags = s.flags || [];
  let focus = FOCUS[s.gui_focus_name] ? t(FOCUS[s.gui_focus_name]) : (s.gui_focus_name || "–");
  if (flags.includes("docked")) focus += " · " + t("DOCKED");
  else if (flags.includes("landed")) focus += " · " + t("LANDED");
  else if (flags.includes("supercruise")) focus += " · SC";
  if (flags.includes("scooping")) focus += " · SCOOP";
  document.getElementById("sb-focus").textContent = focus;
  renderCombat(s.combat);
}

// M8: combat mode - ALERT (shot at, interdicted) or READY (hardpoints out).
// The body class lets a theme repaint the whole FIS (T1 tokens); the state
// ends by itself at `until`, so a quiet game still calms the display down.
const COMBAT_WHY = { attacked: N_("under attack"), shields_down: N_("shields down"), hull_hit: N_("hull hit"),
  interdicted: N_("interdicted"), interdicted_now: N_("interdiction"), danger: N_("danger"),
  hardpoints: N_("hardpoints out"), target: N_("target locked") };
function renderCombat(c) {
  const level = c && c.level;
  document.body.classList.toggle("combat-alert", level === "alert");
  document.body.classList.toggle("combat-ready", level === "ready");
  const cell = document.getElementById("sb-combat");
  if (!cell) return;
  cell.hidden = !level;
  cell.className = "sb-cell sb-combat " + (level || "");
  if (level) {
    document.getElementById("sb-combat-v").textContent = (level === "alert" ? t("COMBAT") : t("WEAPONS READY"));
    cell.title = (c.reasons || []).map(r => t(COMBAT_WHY[r] || r)).join(" · ");
  }
  if (c && c.until) {
    const ms = c.until * 1000 - Date.now() + 500;
    if (ms > 0 && ms < 120000) later("combat", ms, () => refresh("ship"));
  }
}

function tickClock() {
  const d = new Date();
  document.getElementById("sb-clock").textContent =
    d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}
setInterval(tickClock, 10000);
tickClock();

function setLed(state) {
  const led = document.getElementById("sb-led");
  led.className = "led " + state;
  led.title = t({ "": N_("connected"), wait: N_("connecting …"), off: N_("no connection to the FIS service") }[state] || "");
}

// ---------------------------------------------------------------- live push
let lastFix;
setLed("wait");
subscribe({
  open() { store.connected = true; setLed(""); },
  error(rs) { store.connected = false; setLed(rs === 0 ? "wait" : "off"); },
  snapshot(data) { store.live = data; refresh("all"); },
  // the link went silent and is opened again (api.js watchdog)
  stale() { store.connected = false; setLed("wait"); },
  // the server's watchdog state: a reader that stalled shows as a dim LED
  ping(data) {
    if (data && data.poll_age_s !== null && data.poll_age_s > 20) setLed("off");
    else if (store.connected) setLed("");
  },
  jump() {
    refresh("all");
    if (mounted.has("galaxy") && store.view === "galaxy") later("galaxy", 1500, () => galaxy.update(ctx, "data"));
    if (autoView() && store.view !== "planet") show("tactical");
  },
  target() {
    // E5: the SHIP sheet shows destination and locked ship - follow them
    if (mounted.has("ship") && store.view === "ship") later("shipview", 400, () => ship.update(ctx, "data"));
    later("target", 250, async () => {
      await refresh("briefing"); await refresh("ship");
      if (autoView() && store.briefing && store.briefing.target && store.view !== "planet") show("briefing");
    });
  },
  scan() { later("scan", 1200, () => { refresh("system"); refresh("planet"); }); },
  status(data) {
    later("status", 400, () => refresh("ship"));
    // the ship panel follows Status.json (lamps, pips, fuel) about once a second
    if (mounted.has("ship") && store.view === "ship") later("shipview", 900, () => ship.update(ctx, "data"));
    if (mounted.has("surface")) later("surface", 1000, () => surface.update(ctx, "data"));
    // mining: cargo changes with every tonne (Status.json Cargo) - the live block follows
    if (mounted.has("mining") && store.view === "mining") later("mininglive", 1200, () => mining.update(ctx, "live"));
    // landed, in the SRV or on foot: the surface map is what matters now
    if (autoView() && store.view === "tactical" && data && data.on_surface) show("surface");
    // a new reference body (Status.json near a planet) moves LAST FIX at once
    const fix = data && data.fix;
    if (fix !== undefined && fix !== lastFix) {
      lastFix = fix;
      later("fix", 600, () => refresh("system"));
      later("approach", 700, () => refresh("briefing"));   // known points on the body ahead
    }
    later("status-sys", 15000, () => refresh("system"));    // LAST FIX ageing
  },
});

// minute tick: fix age labels; carrier sheet every minute while shown
setInterval(() => {
  if (store.view === "tactical") refresh("system");
  if (store.view === "carrier") carrier.update(ctx, "data");
  if (store.view === "mining") mining.update(ctx, "data");
}, 60000);

show(SOLO || ALIAS[location.hash.slice(1)] || (location.hash || "#tactical").slice(1));
