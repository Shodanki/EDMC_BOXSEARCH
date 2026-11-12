// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// VEHICLE – the surface vehicle out now (SRV Scarab, SRV Rhino, Nomad) or the
// last trip. Only what the game writes: type and edition (Launch event), the
// vehicle's own tank, cargo and refined tonnes, position and heading, the
// switches (Status.json flags), samples and landings, and how far the ship is.
// Hull, ammunition and modules of a vehicle are in no game file.
// SYNTHESIS (V1c): the recipes per tier as you made them (Synthesis events)
// and how often each can still be made from the materials on board.

import { getJSON } from "../api.js";
import { el, frame, fmt, chip, kv, num, withPopout, minutesAgo } from "../ui.js";
import { t, N_ } from "../i18n.js";

const FLAG = {
  lights: N_("LIGHTS"), high_beam: N_("HIGH BEAM"), handbrake: N_("HANDBRAKE"), drive_assist: N_("DRIVE ASSIST"),
  turret: N_("TURRET"), under_ship: N_("UNDER THE SHIP"), night_vision: N_("NIGHT VISION"), analysis: N_("ANALYSIS MODE"),
  hardpoints: N_("WEAPONS OUT"), cargo_scoop: N_("CARGO SCOOP"), shields: N_("SHIELDS"), danger: N_("DANGER"),
  low_fuel: N_("FUEL LOW"), gear: N_("GEAR DOWN"),
};
const FLAG_CLS = { danger: "alert", low_fuel: "warn", hardpoints: "warn" };
const KIND = { fuel: N_("REFUEL"), ammo: N_("AMMO"), repair: N_("REPAIR") };
const TIER = { basic: N_("Basic"), standard: N_("Standard"), premium: N_("Premium") };
// material names as the journal writes them (lower case); others come with
// the game's own name from the server
const MAT = { sulphur: N_("Sulphur"), phosphorus: N_("Phosphorus"), nickel: N_("Nickel"),
  manganese: N_("Manganese"), vanadium: N_("Vanadium"), molybdenum: N_("Molybdenum"), iron: N_("Iron"),
  arsenic: N_("Arsenic"), mercury: N_("Mercury"), technetium: N_("Technetium"),
  mechanicalequipment: N_("Mechanical Equipment") };
const COMPASS = [N_("N"), N_("NE"), N_("E"), N_("SE"), N_("S"), N_("SW"), N_("W"), N_("NW")];

let root = null, data = null, busy = false;

export function mount(r) {
  root = r;
  root.classList.add("vehicle-view");
}

export async function update(ctx, reason) {
  if (!root || busy) return;
  busy = true;
  try { data = await getJSON("/api/vehicle"); } catch (e) { data = null; }
  busy = false;
  render();
}

function edition(e) {
  if (!e) return null;
  return chip(t("{e} edition", { e: e.charAt(0).toUpperCase() + e.slice(1) }), "val");
}

function dist(m) {
  if (m === null || m === undefined) return "–";
  return m >= 1000 ? fmt(m / 1000, 2) + " km" : fmt(m, 0) + " m";
}

function compass(deg) {
  return t(COMPASS[Math.round(((deg % 360) + 360) % 360 / 45) % 8]);
}

function arrow(deg) {
  return el("span", { class: "vh-arrow", style: { transform: "rotate(" + deg + "deg)" }, text: "▲" });
}

function stamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function synthRow(r) {
  const mat = (m) => (MAT[m.key] ? t(MAT[m.key]) : m.name);
  const byKey = Object.fromEntries(r.materials.map((m) => [m.key, m]));
  const label = r.kind ? t(TIER[r.tier] || r.tier) : r.name;
  const note = r.missing.length
    ? t("missing: {m}", { m: r.missing.map((k) => mat(byKey[k])).join(", ") })
    : r.limit ? t("limited by {m} ({n})", { m: mat(byKey[r.limit]), n: byKey[r.limit].have }) : "";
  return el("div", { class: "vh-syn" },
    el("span", { class: "c-dim", text: label }),
    el("span", { class: "vh-syn-n " + (r.can ? "c-green" : "c-amber"), text: r.can === null ? "–" : fmt(r.can, 0) }),
    el("span", { class: "small" },
      el("span", { text: r.materials.map((m) => mat(m) + " " + m.need + "/" + m.have).join(" · ") }),
      note ? el("span", { class: "c-dim", text: " · " + note }) : null,
      el("span", { class: "c-dim", text: " · " + t("made {n}× · last {d}", { n: r.made, d: stamp(r.last) }) })));
}

function synthesis() {
  const S = data.synthesis;
  if (!S) return null;
  const body = [];
  for (const k of S.kinds) {
    const rows = S.recipes.filter((r) => r.kind === k.kind);
    body.push(el("div", { class: "vh-syn-kind" }, t(KIND[k.kind])));
    body.push(...rows.map(synthRow));
    if (k.not_seen.length) body.push(el("div", { class: "c-dim small",
      text: t("not made yet: {t}", { t: k.not_seen.map((x) => t(TIER[x])).join(", ") }) }));
  }
  const other = S.recipes.filter((r) => !r.kind);
  if (other.length) {
    body.push(el("div", { class: "vh-syn-kind" }, t("MADE IN THE VEHICLE")));
    body.push(...other.map(synthRow));
  }
  body.push(el("div", { class: "c-dim small vh-note", text: S.recipes.length
    ? t("Learnt from your own synthesis - a tier appears once you have made it. Per row: material need/on board. Stock as of {d}.", { d: stamp(S.base_ts) || "–" })
    : t("No synthesis yet - make fuel, ammunition or a repair once in the vehicle; its recipe and how often you can make it again follow here.") }));
  return frame(t("SYNTHESIS"), t("your own recipes"), body, { appear: false, cls: "vh-synth" });
}

function render() {
  root.replaceChildren();
  if (!data) {
    root.append(frame(t("VEHICLE"), "", el("div", { class: "empty", text: t("No data from the FIS service.") })));
    return;
  }
  const v = data.vehicle || data.last;
  if (!v) {
    root.append(el("div", { class: "vh-grid" },
      frame(t("VEHICLE"), "", el("div", { class: "empty" },
        t("No vehicle out."), el("br"),
        el("span", { class: "c-dim", text: t("Launch the SRV or the Nomad - type, tank, cargo and position follow here.") }))),
      synthesis()));
    return;
  }
  const live = !!data.vehicle;
  const state = live
    ? (v.on_foot ? t("you are on foot – the vehicle waits") : v.nomad ? (v.flying ? t("flying") : t("landed")) : t("driving"))
    : (v.how === "lost" ? t("lost") : t("back aboard")) + (v.ended ? " · " + minutesAgo(Math.max(0, Math.round((Date.now() / 1000 - v.ended) / 60))) : "");
  const head = [
    el("div", { class: "vh-name" }, el("span", { class: "c-cyan", text: v.name || t("vehicle") }), " ", edition(v.edition)),
    kv([
      [t("STATE"), el("span", { class: live ? (v.on_foot ? "c-amber" : "c-green") : (v.how === "lost" ? "c-red" : "c-dim"), text: state })],
      [t("OUT FOR"), v.minutes !== null && v.minutes !== undefined ? fmt(v.minutes, 0) + " min" : null],
      [t("PIPS"), v.pips ? v.pips.map((p) => fmt(p / 2, p % 2 ? 1 : 0)).join(" · ") : null],
      [t("FIRE GROUP"), v.fire_group !== null && v.fire_group !== undefined ? String.fromCharCode(65 + v.fire_group) : null],
    ]),
  ];
  const tank = [kv([
    [t("FUEL"), v.fuel !== null && v.fuel !== undefined ? num(v.fuel, 2, "t") : null],
    [t("AT LAUNCH"), v.fuel_start !== null && v.fuel_start !== undefined ? fmt(v.fuel_start, 2) + " t" : null],
    [t("USED"), v.fuel_used !== null && v.fuel_used !== undefined ? fmt(v.fuel_used, 3) + " t" : null],
  ])];
  if (v.fuel_start) {
    const pct = Math.max(0, Math.min(100, 100 * (v.fuel || 0) / v.fuel_start));
    tank.push(el("div", { class: "bar vh-fuel" + (pct < 25 ? " alert" : pct < 50 ? " warn" : "") },
      el("i", { style: { width: pct.toFixed(1) + "%" } })));
    tank.push(el("div", { class: "c-dim small", text: t("compared with the tank at launch") }));
  }
  const cargo = [kv([
    [t("CARGO"), num(v.cargo || 0, 0, "t")],
    [t("MATERIALS"), v.materials ? fmt(v.materials, 0) : null],
  ])];
  const ref = Object.entries(v.refined || {});
  if (ref.length) cargo.push(el("div", { class: "vh-list" }, ...ref.sort((a, b) => b[1] - a[1]).map(([m, n]) =>
    el("div", {}, el("span", { class: "num", text: fmt(n, 0) + " t" }), " " + m))));
  const where = [];
  if (v.pos) {
    where.push(kv([
      [t("BODY"), v.pos.body],
      ["LAT / LON", fmt(v.pos.lat, 4) + " / " + fmt(v.pos.lon, 4)],
      [t("ALTITUDE"), v.pos.alt !== null && v.pos.alt !== undefined ? fmt(v.pos.alt, 0) + " m" : null],
      [t("HEADING"), v.pos.heading !== null && v.pos.heading !== undefined ? fmt(v.pos.heading, 0) + "° " + compass(v.pos.heading) : null],
    ]));
  }
  if (v.ship) {
    const rel = v.pos && v.pos.heading !== null && v.pos.heading !== undefined ? v.ship.bearing - v.pos.heading : v.ship.bearing;
    where.push(el("div", { class: "vh-ship" }, arrow(rel),
      el("span", {}, el("span", { class: "k", text: t("SHIP") + " " }), el("span", { class: "num", text: dist(v.ship.dist_m) }),
        el("span", { class: "c-dim", text: " · " + fmt(v.ship.bearing, 0) + "° " + compass(v.ship.bearing) }))));
    where.push(el("div", { class: "c-dim small", text: t("where you left the ship; the arrow is relative to your heading") }));
  }
  const switches = (v.flags || []).map((f) => chip(t(FLAG[f] || f), FLAG_CLS[f] || ""));
  const work = kv([
    [t("BIO SCANS"), v.samples ? fmt(v.samples, 0) : null],
    [t("LANDINGS"), v.nomad && v.landings ? fmt(v.landings, 0) : null],
  ]);
  root.append(el("div", { class: "vh-grid" },
    withPopout(frame(t("VEHICLE"), live ? t("out now") : t("last trip"), head, { appear: false }), "vehicle"),
    frame(t("TANK"), t("the vehicle's own"), tank, { appear: false, kind: v.fuel_start && v.fuel / v.fuel_start < 0.25 ? "warn" : "" }),
    frame(t("CARGO"), v.type === "mev_rhino" ? t("Rhino: refined from rigs") : "", cargo, { appear: false }),
    frame(t("POSITION"), "", where.length ? where : el("div", { class: "c-dim", text: "–" }), { appear: false }),
    frame(t("SWITCHES"), "Status.json", switches.length ? el("div", {}, ...switches) : el("div", { class: "c-dim", text: live && v.on_foot ? t("on foot") : "–" }), { appear: false }),
    frame(t("ACTIVITY"), "", [work, el("div", { class: "c-dim small vh-note",
      text: t("Hull, ammunition and modules of a vehicle are in no game file - the edition is the pack it was bought in.") })], { appear: false }),
    synthesis()));
}
