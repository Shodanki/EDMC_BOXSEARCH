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

const VIEWS = { briefing, tactical, planet, surface, atlas, ship, carrier, galaxy };
// ?solo=ship: one view alone in its own window (second screen, tablet)
const SOLO = (() => { const v = new URLSearchParams(location.search).get("solo"); return v && VIEWS[v] ? v : null; })();
if (SOLO) document.body.classList.add("solo");

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
const PINNED = (/^\d+$/.exec(new URLSearchParams(location.search).get("system") || "") || [null])[0];

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
  document.body.classList.toggle("scanlines", document.getElementById("opt-scan").checked);
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
const ALIAS = { system: "tactical", planetinfo: "planet" };
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
    "6": "atlas", "7": "ship", "8": "carrier" };
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
  jump() {
    refresh("all");
    if (mounted.has("galaxy") && store.view === "galaxy") later("galaxy", 1500, () => galaxy.update(ctx, "data"));
    if (autoView() && store.view !== "planet") show("tactical");
  },
  target() {
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
    // landed, in the SRV or on foot: the surface map is what matters now
    if (autoView() && store.view === "tactical" && data && data.on_surface) show("surface");
    // a new reference body (Status.json near a planet) moves LAST FIX at once
    const fix = data && data.fix;
    if (fix !== undefined && fix !== lastFix) { lastFix = fix; later("fix", 600, () => refresh("system")); }
    later("status-sys", 15000, () => refresh("system"));    // LAST FIX ageing
  },
});

// minute tick: fix age labels; carrier sheet every minute while shown
setInterval(() => {
  if (store.view === "tactical") refresh("system");
  if (store.view === "carrier") carrier.update(ctx, "data");
}, 60000);

show(SOLO || ALIAS[location.hash.slice(1)] || (location.hash || "#tactical").slice(1));
