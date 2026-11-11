// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// SHIP – the ship at a glance, for the pilot, the engineer and the loadmaster.
//
// Top: an annunciator panel like a fighter's – WARNING (red, act now),
// CAUTION (amber, needs attention), ADVISORY (cyan, a state you set). Every
// lamp has a fixed place and stays dark when off, so a glance shows what changed.
// Below: a schematic cutaway (our own drawing, not to scale – the game files
// name slots, not positions), the engineer's column (power, modules, damage
// and function report) and the loadmaster's column (cargo, fuel, locker).

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";

const LAMP = {
  hull_crit: N_("HULL CRITICAL"), overheat: N_("OVERHEAT"), fuel_crit: N_("FUEL CRITICAL"),
  danger: N_("DANGER"), interdicted: N_("INTERDICTION"), canopy: N_("CANOPY BREACH"),
  shutdown: N_("SYSTEMS SHUTDOWN"), oxygen: N_("OXYGEN LOW"),
  shields_down: N_("SHIELDS DOWN"), hull: N_("HULL"), module_dmg: N_("MODULE DAMAGE"),
  module_off: N_("MODULE OFF"), ammo: N_("AMMO"), low_fuel: N_("FUEL LOW"), heat: N_("HEAT"),
  silent: N_("SILENT RUNNING"), fa_off: N_("FA OFF"),
  lights: N_("LIGHTS"), night_vision: N_("NIGHT VISION"), gear: N_("GEAR DOWN"),
  scoop: N_("CARGO SCOOP"), hardpoints: N_("HARDPOINTS"), supercruise: N_("SUPERCRUISE"),
  scooping: N_("FUEL SCOOPING"), fsd_charging: N_("FSD CHARGING"), fsd_cooldown: N_("FSD COOLDOWN"),
  mass_locked: N_("MASS LOCK"), analysis: N_("ANALYSIS MODE"), docked: N_("DOCKED"), landed: N_("LANDED"),
};
const LEVEL = { warning: N_("WARNING"), caution: N_("CAUTION"), advisory: N_("ADVISORY") };
const GROUP = { hardpoints: N_("HARDPOINTS"), utility: N_("UTILITY"), core: N_("CORE"), optional: N_("OPTIONAL") };
const MAT = { carbon: N_("Carbon"), vanadium: N_("Vanadium"), germanium: N_("Germanium"), arsenic: N_("Arsenic"),
  cadmium: N_("Cadmium"), niobium: N_("Niobium"), yttrium: N_("Yttrium"), polonium: N_("Polonium") };
const GRADE = { basic: N_("Basic"), standard: N_("Standard"), premium: N_("Premium") };
const HAZ = {
  UnderAttack: N_("under attack"), Interdicted: N_("interdicted by {by}"), EscapeInterdiction: N_("escaped interdiction by {by}"),
  HullDamage: N_("hull at {pct} %"), HeatWarning: N_("heat warning"), HeatDamage: N_("heat damage"),
  ShieldState: N_("shields down"), CockpitBreached: N_("cockpit breached"), SystemsShutdown: N_("systems shut down"),
  Died: N_("ship destroyed"), JetConeDamage: N_("jet cone damaged {m}"), JetConeBoost: N_("FSD supercharged ×{b}"),
  FighterDestroyed: N_("fighter destroyed"), SRVDestroyed: N_("SRV destroyed"),
};
const REPORT = {
  module_damaged: N_("{w} at {v} %"), module_off: N_("{w} switched off"), ammo_empty: N_("{w}: ammunition empty"),
  ammo_low: N_("{w}: ammunition {v} %"), afmu: N_("AFMU repaired {w} to {v} %"),
  power_over: N_("power draw {v} % of the power plant"),
};

let root = null, data = null, busy = false;

export function mount(r) {
  root = r;
  root.classList.add("ship-view");
  window.addEventListener("fis-layout", () => { if (data) render(); });
}

export async function update(ctx, reason) {
  if (!root || busy) return;
  busy = true;
  try { data = await getJSON("/api/shipstatus"); } catch (e) { data = null; }
  busy = false;
  render();
}

const pct = (v) => (v === null || v === undefined ? null : Math.round(v * 100));
function hcls(h) { return h === null || h === undefined ? "" : h < 0.5 ? "bad" : h < 0.8 ? "warn" : "ok"; }
function stamp(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function render() {
  if (!root) return;
  root.replaceChildren();
  if (!data || data.empty) {
    root.append(frame(t("SHIP"), "", el("div", { class: "empty" }, t("NO SHIP DATA"), el("br"),
      el("span", { class: "c-dim", text: t("Log in to the game – the fitting is written at start, docking and outfitting.") }))));
    return;
  }
  // left: the picture and the hold; right (the wide side): report and the
  // engineer's module list, which needs the room (user, 05.11.2026)
  root.append(annunciator(), el("div", { class: "sh-grid" },
    el("div", { class: "sh-col sh-left" }, cutaway(), logistics(), jumponium()),
    el("div", { class: "sh-col sh-right" }, target(), unsold(), report(), hazards(), engineer())));
}

// ------------------------------------------------------------ unsold data (M4)
// What a destroyed ship would cost in data: exobiology since it was sold
// (valued from your own sales), exploration data only counted.
function unsold() {
  const U = data.unsold;
  if (!U) return null;
  const B = U.bio, X = U.exploration;
  if (!B.count && !X.systems) return frame(t("UNSOLD DATA"), "", el("div", { class: "c-dim", text: t("Nothing unsold - all data is cashed in.") }), { appear: false });
  const Mcr = (v) => fmt(v / 1e6, 1) + " M Cr";
  const rows = [];
  if (B.count) {
    rows.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Exobiology") + " " }),
      el("span", { class: "c-amber", text: t("{n} analysed, not sold", { n: B.count }) + (B.value ? " · ≈ " + Mcr(B.value) : "") }),
      B.first ? el("span", { class: "c-green", text: " · " + t("{n} with first-footfall bonus ×5", { n: B.first }) }) : null));
    if (B.unknown) rows.push(el("div", { class: "c-dim small", text: t("{n} species without a known value (never sold by you)", { n: B.unknown }) }));
    for (const x of B.items.slice(-5)) rows.push(el("div", { class: "small" }, (x.footfall ? "★ " : "◐ ") + (x.variant || x.species),
      el("span", { class: "c-dim", text: (x.system ? " · " + x.system : "") + (x.value ? " · " + Mcr(x.value) : "") })));
  }
  if (X.systems) rows.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Exploration") + " " }),
    el("span", { text: t("{s} systems · {b} bodies · {m} mapped", { s: X.systems, b: X.bodies, m: X.mapped }) })));
  // risk (user 11.11.): low below 50 M, moderate from 50 M, high from 100 M;
  // first discoveries and first-footfall biology are what cannot be had again
  const RISK = { low: [N_("RISK LOW"), "c-green"], moderate: [N_("RISK MODERATE"), "c-amber"], high: [N_("RISK HIGH"), "c-red"] };
  if (U.risk && RISK[U.risk]) rows.unshift(el("div", { class: "pl-line" }, el("span", { class: RISK[U.risk][1], text: t(RISK[U.risk][0]) }),
    el("span", { class: "c-dim", text: " · " + t("moderate from {m} M, high from {h} M Cr", { m: fmt(U.risk_cr.moderate / 1e6, 0), h: fmt(U.risk_cr.high / 1e6, 0) }) })));
  // data that went down with the ship - planned again in SYSTEM until redone
  if (U.lost_systems && U.lost_systems.length) {
    rows.push(el("div", { class: "c-red pl-line", text: "✖ " + t("Lost in a crash, to redo:") }));
    for (const s of U.lost_systems.slice(0, 5)) rows.push(el("div", { class: "small" }, (s.name || "?") + " ",
      el("span", { class: "c-dim", text: [s.scan ? t("{n} scans", { n: s.scan }) : null, s.map ? t("{n} maps", { n: s.map }) : null,
        s.bio.length ? s.bio.join(", ") : null, s.ts ? String(s.ts).slice(0, 10) : null].filter(Boolean).join(" · ") })));
  }
  if (U.first_systems || U.footfall_bio) rows.push(el("div", { class: "c-violet" }, "★ " + [
    U.first_systems ? t("{n} systems discovered first by you", { n: U.first_systems }) : null,
    U.footfall_bio ? t("{n} species on bodies of your first footfall", { n: U.footfall_bio }) : null].filter(Boolean).join(" · ")));
  rows.push(el("div", { class: "c-dim small", text: t("Lost if the ship is destroyed. Values from your own sales; the ×5 bonus only on bodies of your first footfall; exploration data only counted.") }));
  if (U.advice === "sell") rows.push(el("div", { class: "c-red", text: t("A lot at stake - consider selling at the next station or carrier with Vista Genomics / Universal Cartographics.") }));
  return frame(t("UNSOLD DATA"), B.value ? "≈ " + Mcr(B.value) : "", rows, { cls: "sh-unsold", appear: false,
    kind: U.risk === "high" ? "alert" : U.advice || U.risk === "moderate" ? "warn" : "" });
}

// ------------------------------------------------------------ target (E5)
// What is selected in the game right now: destination (Status.json), FSD
// target (galaxy map) and the locked ship as far as it is scanned.
const LEGAL_BAD = new Set(["Wanted", "WantedEnemy", "Enemy", "Hunter", "Thargoid"]);
function target() {
  const T = data.target || {};
  const rows = [];
  const line = (k, v, cls = "") => el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: k + " " }), el("span", { class: cls, text: v }));
  const d = T.destination;
  if (d) {
    const where = d.here ? t("in this system") : (d.system || t("another system"));
    rows.push(line(t("Destination"), (d.name || d.body || "?") + " · " + where
      + (d.here && d.arrival_ls !== null && d.arrival_ls !== undefined ? " · " + fmt(d.arrival_ls, 0) + " LS" : ""), "c-cyan"));
  }
  if (T.fsd && T.fsd.name && !(d && !d.here && d.system === T.fsd.name))
    rows.push(line(t("FSD target"), T.fsd.name + (T.fsd.star_class ? " [" + T.fsd.star_class + "]" : "")
      + (T.fsd.remaining_jumps ? " · " + t("{n} jumps left", { n: T.fsd.remaining_jumps }) : "")));
  const sh = T.ship;
  if (sh) {
    rows.push(line(t("Locked"), sh.ship + (sh.pilot ? " · " + sh.pilot : "") + (sh.rank ? " (" + sh.rank + ")" : ""), "c-amber"));
    const bits = [];
    if (sh.legal) bits.push(el("span", { class: LEGAL_BAD.has(sh.legal) ? "c-red" : "c-green", text: sh.legal }));
    if (sh.bounty) bits.push(el("span", { class: "c-amber", text: " · " + t("bounty {n} Cr", { n: fmt(sh.bounty, 0) }) }));
    if (sh.faction) bits.push(el("span", { class: "c-dim", text: " · " + sh.faction }));
    if (sh.power) bits.push(el("span", { class: "c-dim", text: " · " + sh.power }));
    if (bits.length) rows.push(el("div", { class: "pl-line" }, ...bits));
    if (sh.shield !== undefined || sh.hull !== undefined)
      rows.push(line(t("Shield / hull"), (pct(sh.shield) ?? "–") + " % / " + (pct(sh.hull) ?? "–") + " %", hcls(sh.hull)));
    if (sh.subsystem) rows.push(line(t("Subsystem"), sh.subsystem + (sh.subsystem_health !== null && sh.subsystem_health !== undefined ? " " + pct(sh.subsystem_health) + " %" : "")));
    if ((sh.stage ?? 3) < 3) rows.push(el("div", { class: "c-dim small", text: t("Scan stage {n} of 3 - keep the target locked for more.", { n: sh.stage ?? 0 }) }));
  }
  if (!rows.length) rows.push(el("div", { class: "c-dim", text: t("Nothing selected - pick a target in the game.") }));
  return frame(t("TARGET"), sh ? t("ship locked") : "", rows, { cls: "sh-tgt", appear: false });
}

// ------------------------------------------------------------ annunciator
function annunciator() {
  const s = data.ship;
  const master = el("div", { class: "ann-master " + data.master },
    el("div", { class: "am-k", text: data.master === "normal" ? t("ALL SYSTEMS") : t(LEVEL[data.master]) }),
    el("div", { class: "am-v", text: data.master === "normal" ? t("NORMAL") : t("CHECK") }));
  const bands = ["warning", "caution", "advisory"].map(lv => el("div", { class: "ann-band " + lv },
    el("div", { class: "ab-k", text: t(LEVEL[lv]) }),
    el("div", { class: "ab-lamps" }, ...data.panel.filter(p => p.level === lv).map(p =>
      el("div", { class: "lamp " + lv + (p.on ? " on" : ""), text: t(LAMP[p.key] || p.key) })))));
  const id = el("div", { class: "ann-id" },
    el("div", { class: "c-cyan sh-name", text: (s.name || s.type || "?") }),
    el("div", { class: "c-dim", text: [s.type, s.ident].filter(Boolean).join(" · ") }),
    el("div", { class: "sh-hull " + hcls(s.hull), text: t("HULL") + " " + (pct(s.hull) ?? "–") + " %" }),
    el("div", { class: "c-dim small", text: data.live ? t("live") : t("game not running – last known state") }));
  return withPopout(frame(t("STATUS"), "", el("div", { class: "ann" }, master,
    el("div", { class: "ann-bands" }, ...bands), id), { cls: "sh-ann", appear: false }), "ship");
}

// ------------------------------------------------------------ cutaway
// Schematic top view: nose up. Hardpoints along the nose by size, utility on
// the spine, core modules on the centre line front to back, optional
// internals on both flanks by size. Colour = integrity, dashed = switched off.
function cutaway() {
  const W = 420, H = 470, cx = W / 2;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("class", "sh-cut");
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    svg.append(n); return n;
  };
  // hull outline (stylised, our own)
  add("path", { d: `M${cx} 18 L${cx + 60} 70 L${cx + 128} 112 L${cx + 160} 300 L${cx + 178} 420 L${cx + 60} 450 L${cx - 60} 450 L${cx - 178} 420 L${cx - 160} 300 L${cx - 128} 112 L${cx - 60} 70 Z`, class: "hull-line" });
  add("path", { d: `M${cx} 40 L${cx} 440`, class: "hull-axis" });
  const box = (x, y, w, h, m, label) => {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "mod " + hcls(m.health) + (m.on === false ? " off" : ""));
    const r = document.createElementNS(NS, "rect");
    Object.entries({ x, y, width: w, height: h, rx: 2 }).forEach(([k, v]) => r.setAttribute(k, v));
    const tt = document.createElementNS(NS, "title");
    tt.textContent = m.name + " · " + (pct(m.health) ?? "–") + " %" + (m.power ? " · " + fmt(m.power, 2) + " MW" : "")
      + " · P" + m.priority + (m.eng ? " · " + m.eng : "") + (m.ammo_pct !== undefined && m.ammo_pct !== null ? " · " + t("ammo") + " " + m.ammo_pct + " %" : "");
    g.append(r, tt);
    if (label) {
      const tx = document.createElementNS(NS, "text");
      tx.setAttribute("x", x + w / 2); tx.setAttribute("y", y + h / 2 + 3.5); tx.setAttribute("text-anchor", "middle");
      tx.textContent = label; g.append(tx);
    }
    svg.append(g);
  };
  const M = data.modules;
  // hardpoints: largest in the middle of the nose
  const hp = [...M.hardpoints].sort((a, b) => (b.size || 0) - (a.size || 0));
  const hpRow = []; hp.forEach((m, i) => (i % 2 ? hpRow.push(m) : hpRow.unshift(m)));
  hpRow.forEach((m, i) => {
    const n = hpRow.length, w = 20 + 6 * (m.size || 1), gap = 4;
    const tot = hpRow.reduce((s, x) => s + 20 + 6 * (x.size || 1) + gap, -gap);
    let x0 = cx - tot / 2; for (let j = 0; j < i; j++) x0 += 20 + 6 * (hpRow[j].size || 1) + gap;
    const dy = Math.abs(i - (n - 1) / 2) * 9;
    box(x0, 96 + dy, w, 16, m, ["", "S", "M", "L", "H"][m.size || 0] || "");
  });
  // utility on the spine
  M.utility.forEach((m, i) => box(cx - 13 - (i % 2 ? -26 : 0) - 13, 140 + Math.floor(i / 2) * 15, 24, 11, m, ""));
  // core along the centre line
  const order = ["Radar", "LifeSupport", "PowerDistributor", "PowerPlant", "FrameShiftDrive", "FuelTank", "MainEngines"];
  const short = { Radar: "SEN", LifeSupport: "LS", PowerDistributor: "PD", PowerPlant: "PP", FrameShiftDrive: "FSD", FuelTank: "FUEL", MainEngines: "THR" };
  let y = 140 + Math.ceil(M.utility.length / 2) * 15 + 8;
  for (const slot of order) {
    const m = M.core.find(x => x.slot === slot); if (!m) continue;
    box(cx - 30, y, 60, 24, m, short[slot]); y += 30;
  }
  const armour = M.core.find(x => x.slot === "Armour");
  if (armour) add("text", { x: cx, y: 465, "text-anchor": "middle", class: "cut-note" }, armour.name);
  // optional internals on both flanks, biggest first
  const opt = [...M.optional].sort((a, b) => (b.size || 0) - (a.size || 0));
  const sideY = [170, 170];
  opt.forEach((m, i) => {
    const side = i % 2, w = 22 + 7 * (m.size || 1), h = 12 + 2 * (m.size || 1);
    const x = side ? cx + 44 + (8 - (m.size || 1)) * 3 : cx - 44 - w - (8 - (m.size || 1)) * 3;
    box(x, sideY[side], w, h, m, String(m.size || ""));
    sideY[side] += h + 5;
  });
  const legend = el("div", { class: "cut-legend" },
    el("span", { class: "lg ok", text: "■ " + t("intact") }), el("span", { class: "lg warn", text: "■ < 80 %" }),
    el("span", { class: "lg bad", text: "■ < 50 %" }), el("span", { class: "lg off", text: "▭ " + t("off") }),
    el("span", { class: "c-dim", text: t("schematic – the game names slots, not positions") }));
  return frame(t("CUTAWAY"), stamp(data.ship.loadout_ts), [svg, legend], { cls: "sh-cutf", appear: false });
}

// ------------------------------------------------------------ engineer
function engineer() {
  const p = data.power;
  const cap = p.capacity || Math.max(p.draw, 1);
  const prio = el("div", { class: "pw-stack" });
  let prev = 0;
  p.by_priority.forEach((v, i) => {
    const w = Math.max(0, (v - prev) / cap * 100); prev = v;
    prio.append(el("i", { class: "p" + (i + 1), style: { width: w.toFixed(1) + "%" }, title: "P" + (i + 1) + ": " + fmt(v, 1) + " MW" }));
  });
  const pips = el("div", { class: "pips" }, ...["SYS", "ENG", "WEP"].map((k, i) => el("div", { class: "pip" },
    el("span", { class: "c-dim", text: k }),
    el("span", { class: "pip-bar" }, ...[0, 1, 2, 3].map(j => el("i", { class: (p.pips[i] || 0) > j ? "on" + ((p.pips[i] || 0) - j < 1 ? " half" : "") : "" }))))));
  const power = el("div", { class: "pw" },
    el("div", { class: "pw-head" },
      el("span", { text: t("POWER") }),
      el("span", { class: p.load_pct > 100 ? "c-red" : p.load_pct > 90 ? "c-amber" : "c-green",
        text: fmt(p.draw, 1) + (p.capacity ? " / " + fmt(p.capacity, 1) + " MW · " + p.load_pct + " %" : " MW · " + t("plant capacity unknown")) })),
    prio,
    el("div", { class: "c-dim small", text: t("stack by priority P1 … P5 (P1 switches off last)") }),
    pips);
  const groups = Object.entries(data.modules).map(([g, list]) => el("div", { class: "mg" },
    el("div", { class: "mg-h", text: t(GROUP[g]) + " · " + list.length }),
    ...list.map(m => el("div", { class: "mrow " + hcls(m.health) + (m.on === false ? " off" : ""), title: m.slot + (m.experimental ? " · " + m.experimental : "") },
      el("span", { class: "m-n", text: m.name }),
      el("span", { class: "m-h" }, el("i", { style: { width: (pct(m.health) ?? 0) + "%" } })),
      el("span", { class: "m-v", text: (pct(m.health) ?? "–") + "%" }),
      el("span", { class: "m-p", text: "P" + m.priority }),
      el("span", { class: "m-w", text: m.power ? fmt(m.power, 2) : "" }),
      el("span", { class: "m-a", text: m.ammo_pct !== undefined && m.ammo_pct !== null ? "▮" + m.ammo_pct + "%" : (m.eng || "") })))));
  const i = data.integrity;
  return frame(t("ENGINEER"), t("min {v} % · {d} damaged · {o} off", { v: pct(i.min) ?? "–", d: i.damaged, o: i.off }),
    [power, el("div", { class: "mgroups" }, ...groups)], { cls: "sh-eng", appear: false });
}

// ------------------------------------------------------------ report
function report() {
  const rows = data.report.map(r => el("div", { class: "rp " + r.level },
    el("span", { class: "rp-l", text: t(LEVEL[r.level]) }),
    el("span", { text: t(REPORT[r.key] || r.key, { w: r.what || "", v: r.value ?? "" }) })));
  const body = rows.length ? rows : [el("div", { class: "rp ok" }, el("span", { class: "rp-l", text: "OK" }),
    el("span", { text: t("All modules intact and switched on.") }))];
  body.push(el("div", { class: "c-dim small", text: t("Module state as of {t} – the game writes it at login, docking and outfitting.", { t: stamp(data.ship.loadout_ts) }) }));
  const s = data.ship;
  body.push(el("div", { class: "kvline" },
    el("span", { class: "c-dim", text: t("Rebuy") }), el("span", { text: fmt(s.rebuy, 0) + " Cr" }),
    el("span", { class: "c-dim", text: t("Value") }), el("span", { text: fmt(s.value, 0) + " Cr" }),
    el("span", { class: "c-dim", text: t("Jump") }), el("span", { text: fmt(s.max_jump, 1) + " ly" })));
  return frame(t("DAMAGE & FUNCTION REPORT"), String(data.report.length), body, { cls: "sh-rep", appear: false });
}

// ------------------------------------------------------------ jumponium (B3)
// FSD injections from the raw materials on board; what limits them and the
// nearest bodies where you measured it
function jumponium() {
  const J = data.jumponium;
  if (!J) return null;
  const mat = (k) => t(MAT[k] || k);
  const have = Object.fromEntries(J.materials.map(m => [m.key, m]));
  const rows = J.ready.map(r => el("div", { class: "jp-row" },
    el("span", { class: "c-dim", text: t(GRADE[r.grade]) + " +" + r.boost + " %" }),
    el("span", { class: "jp-n " + (r.can ? "c-green" : "c-amber"), text: fmt(r.can, 0) }),
    el("span", { class: "small c-dim", text: r.missing.length ? t("missing: {m}", { m: r.missing.map(mat).join(", ") })
      : t("limited by {m} ({n})", { m: mat(r.limit), n: have[r.limit] ? have[r.limit].count : 0 }) })));
  const stock = el("div", { class: "jp-mats" }, ...J.materials.map(m => el("span", {
    class: "chip " + (m.count === 0 ? "warn" : m.count >= m.cap * 0.9 ? "ok" : ""), title: "G" + m.grade + " · max " + m.cap,
    text: mat(m.key) + " " + m.count + "/" + m.cap })));
  const src = Object.entries(J.sources).filter(([, l]) => l.length).map(([k, l]) => el("div", { class: "small" },
    el("span", { class: "c-amber", text: mat(k) + ": " }),
    l.map(s => s.body + " " + fmt(s.pct, 1) + " %" + (s.ly === null ? "" : s.ly < 0.1 ? " · " + t("here") : " · " + fmt(s.ly, 1) + " ly")).join("  |  ")));
  const last = J.synthesised.length ? J.synthesised[J.synthesised.length - 1] : null;
  return frame(t("JUMPONIUM"), J.base_ts ? stamp(Date.parse(J.base_ts) / 1000) : "", [
    ...rows, stock,
    src.length ? el("div", { class: "c-dim small", text: t("Where you measured it (landable, nearest first):") }) : null, ...src,
    last ? el("div", { class: "c-dim small", text: t("Last synthesised: {g} · {d}", { g: t(GRADE[last.grade]), d: stamp(Date.parse(last.ts) / 1000) }) }) : null,
  ], { cls: "sh-jump", appear: false });
}

// ------------------------------------------------------------ hazard log (B7)
function hazards() {
  const H = data.hazards;
  if (!H) return null;
  const c = H.counts || {};
  const tag = (c.danger ? c.danger + " ▲ " : "") + (c.warn ? c.warn + " △" : "");
  const short = (it) => it.body ? it.body : it.system || "";
  const items = H.items.slice(0, 14).map(it => el("div", { class: "hz-row " + it.level },
    el("span", { class: "c-dim", text: new Date(it.t * 1000).toDateString() === new Date().toDateString()
      ? new Date(it.t * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : stamp(it.t) }),
    el("span", { text: t(HAZ[it.kind] || it.kind, { by: it.v.by || "?", pct: it.v.pct, m: it.v.module || "", b: it.v.boost ? fmt(it.v.boost, 1) : "?" })
      + (it.n > 1 ? "  ×" + it.n : "") + (it.kind === "UnderAttack" && it.v.target && it.v.target !== "You" ? " (" + it.v.target + ")" : "") }),
    el("span", { class: "c-dim small", text: short(it) })));
  return frame(t("HAZARD LOG"), tag || t("this session"), items.length ? items
    : el("div", { class: "c-dim", text: t("Nothing happened this session.") }), { cls: "sh-haz", appear: false });
}

// ------------------------------------------------------------ logistics
function logistics() {
  const L = data.logistics;
  const bar = (v, max, cls) => el("span", { class: "lbar " + (cls || "") }, el("i", { style: { width: max ? Math.min(100, 100 * (v || 0) / max).toFixed(1) + "%" : "0" } }));
  const f = L.fuel;
  const rows = [
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Cargo") }), bar(L.used, L.capacity),
      el("span", { text: fmt(L.used, 0) + " / " + fmt(L.capacity, 0) + " t" })),
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Fuel") }), bar(f.main, f.capacity, (f.main / (f.capacity || 1)) < 0.25 ? "warn" : ""),
      el("span", { text: fmt(f.main, 1) + " / " + fmt(f.capacity, 0) + " t" })),
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Reservoir") }), bar(f.reservoir, f.reserve_cap),
      el("span", { text: fmt(f.reservoir, 2) + " / " + fmt(f.reserve_cap, 2) + " t" })),
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Limpets") }), el("span"), el("span", { text: fmt(L.limpets, 0) })),
  ];
  const inv = L.cargo.length ? el("div", { class: "cargo scroll" }, ...L.cargo.map(c => el("div", { class: "cg" + (c.stolen ? " hot" : "") },
    el("span", { text: c.name + (c.stolen ? " ⚠" : "") + (c.mission ? " ◆" : "") }), el("span", { class: "num", text: fmt(c.count, 0) + " t" }))))
    : el("div", { class: "c-dim", text: t("Hold empty.") });
  const lk = L.locker;
  const locker = el("div", { class: "c-dim small", text: t("Ship locker: {i} items · {c} components · {u} consumables · {d} data",
    { i: lk.Items, c: lk.Components, u: lk.Consumables, d: lk.Data }) });
  const bal = L.balance !== null && L.balance !== undefined ? el("div", { class: "small", text: t("Credits") + ": " + fmt(L.balance, 0) + " Cr" }) : null;
  return frame(t("LOGISTICS"), L.free !== null ? t("{n} t free", { n: fmt(L.free, 0) }) : "", [...rows, inv, locker, bal], { cls: "sh-log", appear: false });
}
