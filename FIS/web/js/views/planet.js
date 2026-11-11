// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// PLANET – datasheet of one body.

import { getJSON } from "../api.js";
import { el, frame, fmt, num, chip, hbar, tile, countUp, classDe } from "../ui.js";
import { t, N_, lang } from "../i18n.js";

let root = null;
let current = null;     // datasheet JSON
let currentKey = null;  // "id64/body_id" of `current`
let currentJson = "";   // the same as text: an unchanged answer is not drawn again
let loading = null;
let stale = false;      // something changed while PLANET INFO was hidden

export function mount(r) { root = r; root.classList.add("planet-view"); }

const keyOf = (sel) => sel ? sel.id64 + "/" + sel.body_id : null;

// E3: every scan event (FSS, DSS, bio, codex - of any body, from the journal
// and again from the plugin database) and every jump called load(); each
// answer redrew the whole sheet with its count-up animation, which looked
// like constant reloading. Now: hidden -> only remember that it is stale;
// shown -> fetch, and draw only when the answer differs.
export async function load(ctx) {
  const sel = ctx.store.selected;
  if (!sel) { current = null; currentKey = null; currentJson = ""; if (root && ctx.store.view === "planet") render(ctx); return; }
  if (ctx.store.view !== "planet") { stale = true; return; }
  stale = false;
  const key = keyOf(sel);
  loading = key;
  const data = await getJSON("/api/body/" + key);
  if (loading !== key) return;           // a newer selection won
  const json = JSON.stringify(data);
  if (key === currentKey && json === currentJson) return;   // nothing new: keep the sheet as it is
  current = data; currentKey = key; currentJson = json;
  if (root && ctx.store.view === "planet") render(ctx);
}

// The body of the last fix (approached, scanned, landed ...) is shown by
// itself: when the fix moves to another body, PLANET INFO follows. A body
// picked by hand stays until the fix moves on.
let lastFixKey = null;

export function update(ctx, reason) {
  if (!root) return;
  const sys = ctx.store.system, fix = sys && sys.fix;
  if (fix && fix.body_id !== null && fix.body_id !== undefined) {
    const fk = sys.id64 + ":" + fix.body_id;
    if (fk !== lastFixKey) {
      lastFixKey = fk;
      if (!ctx.store.selected || keyOf(ctx.store.selected) !== keyOf({ id64: sys.id64, body_id: fix.body_id })) {
        ctx.store.selected = { id64: sys.id64, body_id: fix.body_id };
        load(ctx); return;
      }
    }
  }
  if (!ctx.store.selected && ctx.store.system && ctx.store.system.route && ctx.store.system.route.next) {
    // nothing picked yet: show the next stop of the route
    const leg = ctx.store.system.route.legs[ctx.store.system.route.next - 1];
    if (leg) { ctx.store.selected = { id64: ctx.store.system.id64, body_id: leg.body_id }; load(ctx); return; }
  }
  if (reason === "show") {
    if (currentKey === keyOf(ctx.store.selected)) render(ctx);   // the known sheet at once
    if (stale || currentKey !== keyOf(ctx.store.selected)) load(ctx);
  }
}

const ATMO = { CarbonDioxide: "CO₂", SulphurDioxide: "SO₂", Nitrogen: "N₂", Oxygen: "O₂", Water: "H₂O",
  Ammonia: "NH₃", Methane: "CH₄", Argon: "Ar", Neon: "Ne", Helium: "He", Hydrogen: "H₂", Silicates: "Silicates", Iron: "Fe" };
const atmoName = (k) => (k === "Silicates" && lang() === "de") ? "Silikate" : (ATMO[k] || k);
const COMPOSITION = { Rock: N_("Rock"), Metal: N_("Metal"), Ice: N_("Ice") };

// Science report: the server sends facts (fis/science.py), the words are here.
const SECTION = { class: N_("Classification"), record: N_("Record"), atmosphere: N_("Atmosphere and surface"),
  geology: N_("Geology"), biology: N_("Biology"), resources: N_("Resources"), hazards: N_("Hazards"),
  advice: N_("Recommendation") };
const REPORT = {
  star: N_("Class {t} {lum} star, {m} solar masses, {age} million years old."),
  planet: N_("{cls}, radius {r} km, {m} Earth masses, surface gravity {g} g."),
  orbits: N_("Orbits {p}."),
  terraformable: N_("Candidate for terraforming."),
  first_discovery: N_("First discovery: no one scanned this body before us."),
  known_before: N_("Discovered before us."),
  first_mapped: N_("Never mapped before – a first mapping is possible."),
  first_footfall_open: N_("No footfall recorded yet."),
  dss_efficient: N_("Surface mapped efficiently: {p} probes, target {target}."),
  dss_done: N_("Surface mapped with {p} probes (target {target})."),
  atmosphere: N_("{a} atmosphere, {p} atm."),
  no_atmosphere: N_("No atmosphere."),
  temperature: N_("Surface temperature {k} K ({c} °C)."),
  tidal_lock: N_("Tidally locked to its parent."),
  rotation: N_("Rotation period {d} days."),
  volcanism: N_("Volcanism: {v}."),
  no_volcanism: N_("Geologically inactive."),
  geo_signals: N_("{n} geological signals."),
  bio_signals: N_("{n} biological signals, {a} species analysed."),
  bio_open: N_("Not yet sampled: {g}."),
  bio_forecast: N_("Most likely genus: {g} ({p} %)."),
  rare_materials: N_("Rare materials: {m}."),
  jumponium_premium: N_("All materials for premium FSD injection present."),
  jumponium_standard: N_("All materials for standard FSD injection present."),
  jumponium_basic: N_("All materials for basic FSD injection present."),
  rings: N_("{n} ring(s), {c}, reserves {r}."),
  hotspots: N_("Hotspots: {h}."),
  gravity_very_high: N_("Very high gravity ({g} g) – landing and SRV use are dangerous."),
  gravity_high: N_("High gravity ({g} g) – approach carefully."),
  hot: N_("Extreme heat ({k} K) – watch ship temperature."),
  cold: N_("Extreme cold ({k} K)."),
  toxic: N_("Hostile atmosphere: {a}."),
  neutron: N_("Neutron star – jet cones supercharge the FSD but damage the ship; keep out of them otherwise."),
  white_dwarf: N_("White dwarf – jet cones supercharge the FSD but damage the ship."),
  black_hole: N_("Black hole – keep your distance."),
  scoopable: N_("Fuel scooping possible."),
  not_scoopable: N_("Not scoopable – check fuel before the next jump."),
  dss_recommended: N_("Detailed surface scan recommended."),
  landing: N_("Landing possible ({g} g)."),
  sample: N_("{n} biological signal(s) still to sample."),
  bio_complete: N_("Biology complete."),
};
const LEVEL_CLS = { good: "c-green", warn: "c-amber", danger: "c-red", info: "" };

function reportFrame(b) {
  if (!b.report || !b.report.length) return null;
  const rows = [];
  let last = null;
  for (const f of b.report) {
    if (f.section !== last) { rows.push(el("div", { class: "sr-h", text: t(SECTION[f.section] || f.section) })); last = f.section; }
    const v = {};
    // digits by size: 0.0002 Earth masses must not read as 0.00
    const dig = (x) => (x % 1 === 0 ? 0 : Math.abs(x) < 0.01 ? 4 : Math.abs(x) < 10 ? 2 : 0);
    for (const [k, x] of Object.entries(f.v || {})) v[k] = typeof x === "number" ? fmt(x, dig(x)) : (x ?? "–");
    if (f.id === "orbits" && String(f.v.p).startsWith("barycentre")) v.p = t("a barycentre") + String(f.v.p).slice(10);
    rows.push(el("div", { class: "sr-line " + (LEVEL_CLS[f.level] || "") }, t(REPORT[f.id] || f.id, v)));
  }
  rows.push(el("div", { class: "c-dim small", text: t("Rule-based from the journal and the plugin database – no AI.") }));
  const kind = b.report_level === "danger" ? "warn" : b.report_level === "warn" ? "warn" : "hot";
  return frame(t("SCIENCE REPORT"), b.short || b.name, rows, { kind, cls: "sr-frame" });
}

function render(ctx) {
  if (!root) return;
  root.replaceChildren();
  const b = current;
  if (!b) {
    root.append(frame(t("PLANET INFO"), "", el("div", { class: "empty" }, t("NO BODY SELECTED"), el("br"),
      el("span", { class: "c-dim", text: t("Click a body in SYSTEM.") }))));
    return;
  }
  const flags = [];
  if (b.flags.first) flags.push(chip(t("first discovery"), "first"));
  if (b.flags.first_map) flags.push(chip(t("never mapped"), "first"));
  if (b.flags.mapped) flags.push(chip(t("mapped"), "mapped"));
  if (b.flags.footfall) flags.push(chip(t("first footfall"), "ff"));
  if (b.landable) flags.push(chip(t("landable"), "val"));
  if (b.terraform) flags.push(chip(b.terraform === "Terraformable" ? t("terraformable") : b.terraform, "val"));
  if (b.bio.signals) flags.push(chip("Bio ×" + b.bio.signals, "bio"));
  if (b.bio.geo) flags.push(chip("Geo ×" + b.bio.geo, "geo"));

  const head = el("div", { class: "pl-head" },
    el("div", {}, el("h1", { class: "pl-name", text: b.short || b.name }),
      el("div", { class: "c-dim", text: (b.system || "") + " · " + (b.kind === "Star" ? t("Star") + " " + (b.cls || "") : classDe(b.cls)) })),
    el("div", { class: "pl-flags" }, ...flags));

  const tiles = el("div", { class: "tiles" });
  if (b.kind !== "Star") {
    tiles.append(tile(t("Gravity"), num(b.gravity_g, 2), "g"));
  }
  tiles.append(tile(t("Temperature"), num(b.temp_k, 0), "K"));
  if (b.kind !== "Star") tiles.append(tile(t("Pressure"), num(b.pressure_atm, b.pressure_atm && b.pressure_atm < 0.1 ? 4 : 2), "atm"));
  tiles.append(tile("Radius", num(b.radius_km, 0), "km"));
  if (b.mass_em !== null && b.kind !== "Star") tiles.append(tile(t("Mass"), num(b.mass_em, b.mass_em < 0.01 ? 5 : 3), "M⊕"));
  if (b.star) tiles.append(tile(t("Mass"), num(b.star.mass_sol, 3), "M☉"));
  tiles.append(tile(t("Arrival"), num(b.arrival_ls, 0), "LS"));
  tiles.append(tile("Rotation", num(b.rotation_d, 2), "d" + (b.tidal_lock ? " · " + t("locked") : "")));
  if (b.axial_tilt_deg !== null) tiles.append(tile(t("Axial tilt"), num(b.axial_tilt_deg, 1), "°"));
  if (b.orbit.period_d) tiles.append(tile(t("Orbit"), num(b.orbit.period_d, 1), "d"));
  if (b.orbit.ecc !== null) tiles.append(tile(t("Eccentricity"), num(b.orbit.ecc, 3)));
  if (b.orbit.inc_deg !== null && b.orbit.inc_deg !== undefined) tiles.append(tile(t("Inclination"), num(b.orbit.inc_deg, 1), "°"));
  if (b.orbit.sma_ls) tiles.append(tile(t("Semi-major axis"), num(b.orbit.sma_ls, 2), "LS"));
  if (b.orbit.peri_deg !== null && b.orbit.peri_deg !== undefined) tiles.append(tile(t("Periapsis"), num(b.orbit.peri_deg, 1), "°"));

  const extra = [];
  if (b.parent) extra.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Orbits") + " " }),
    String(b.parent).startsWith("barycentre") ? t("a barycentre") + String(b.parent).slice(10) : b.parent));
  if (b.dss) extra.push(el("div", { class: "pl-line " + (b.dss.efficient ? "c-green" : "") },
    el("span", { class: "c-dim", text: "DSS " }), t("{p} probes, target {target}", { p: b.dss.probes, target: b.dss.target })
      + (b.dss.efficient ? " · " + t("efficient") : "") + (b.dss.ts ? " · " + b.dss.ts.slice(0, 10) : "")));
  if (b.visits) extra.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Your visits") + " " }),
    t("{l} landings · {m} marks · last {d}", { l: b.visits.landings, m: b.visits.marks, d: b.visits.last || "–" })));
  const left = [frame(t("DATASHEET"), b.kind === "Star" ? t("Star") : t("Body {n}", { n: b.body_id }), [head, tiles, ...extra], { kind: "hot" })];

  if (b.star) {
    left.push(frame(t("STAR"), "", el("div", { class: "kv" },
      ...[[t("Type"), (b.star.type || "?") + (b.star.subclass ?? "") + " " + (b.star.luminosity || "")],
          [t("Scoopable"), b.star.scoopable ? t("yes") : t("no")],
          [t("Abs. magnitude"), fmt(b.star.abs_mag, 2)],
          [t("Age"), t("{n} million years", { n: fmt(b.star.age_my, 0) })]].flatMap(([k, v]) => [el("div", { class: "k", text: k }), el("div", { class: "v", text: v })]))));
  }

  // atmosphere & surface
  const atmo = [];
  atmo.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Atmosphere") + " " }),
    el("span", { text: b.atmosphere || (b.atmo_type && b.atmo_type !== "None" ? b.atmo_type : t("none")) })));
  for (const [k, v] of b.atmo_comp) atmo.push(hbar(atmoName(k), v, 100, fmt(v, 1) + " %"));
  atmo.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Volcanism") + " " }),
    el("span", { class: b.volcanism ? "c-amber" : "", text: b.volcanism || t("none") })));
  if (b.composition.length) {
    atmo.push(el("h3", { text: t("Composition"), style: { marginTop: "8px" } }));
    for (const [k, v] of b.composition) atmo.push(hbar(COMPOSITION[k] ? t(COMPOSITION[k]) : k, v, 100, fmt(v, 1) + " %", "green"));
  }
  // E2: the science report sits under the datasheet, the signals below it;
  // the right column (atmosphere, biology, materials, rings) moves up
  const rep = reportFrame(b);
  if (rep) left.push(rep);
  const right = [];
  if (b.kind !== "Star") right.push(frame(t("ATMOSPHERE · SURFACE"), "", atmo));

  // biology
  const bio = [];
  if (b.bio.signals || b.bio.species.length || b.bio.prediction.length) {
    bio.push(el("div", { class: "pl-line" },
      el("span", { class: "c-amber", text: t(b.bio.signals === 1 ? "{n} bio signal" : "{n} bio signals", { n: b.bio.signals }) }),
      el("span", { class: "c-dim", text: " · " + t("{n} analysed", { n: b.bio.analysed }) })));
    if (b.bio.genera.length) bio.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Genera (DSS)") + " " }), b.bio.genera.join(", ")));
    for (const s of b.bio.species) bio.push(el("div", { class: "pl-line c-green" }, "✓ " + (s.variant || s.species),
      el("span", { class: "c-dim", text: (s.date ? " · " + s.date : "")
        + (s.value ? " · " + fmt(s.value / 1e6, 2) + " M Cr" + (s.bonus ? " (+" + fmt(s.bonus / 1e6, 2) + " M " + t("first logged") + ")" : "") : "") })));
    if (b.bio.prediction.length) {
      bio.push(el("h3", { text: b.bio.genera.length ? t("Forecast (for comparison)") : t("Forecast – possible here"), style: { marginTop: "8px" } }));
      for (const p of b.bio.prediction) bio.push(hbar(p.genus, p.score, 1, Math.round(p.score * 100) + " %", "amber"));
      bio.push(el("div", { class: "c-dim small", text: (b.bio.model || "") + " – " + t("rule based on your own finds, no AI.") }));
    }
    right.push(frame(t("BIOLOGY"), "", bio, { kind: b.bio.signals > b.bio.analysed ? "warn" : "" }));
  }

  if (b.materials.length) {
    const mats = b.materials.map(([k, v]) => hbar(k, v, b.materials[0][1] || 1, fmt(v, 1) + " %", "violet"));
    right.push(frame(t("MATERIALS"), b.materials.length + "", mats));
  }
  if (b.rings.length || b.hotspots.length) {
    // E11: each ring with its own hotspots below it ("Tritium ×2, Platinum");
    // hotspots whose ring is not in the ring list stay listed at the end
    const hsText = (hs) => hs.map(h => h.material + (h.count > 1 ? " ×" + h.count : "")).join(", ");
    const ringNames = new Set(b.rings.map(r => r.name));
    const rr = [];
    for (const r of b.rings) {
      rr.push(el("div", { class: "pl-line" }, el("span", { class: "c-cyan", text: (r.name || "").replace(b.name, "").trim() || "Ring" }),
        el("span", { class: "c-dim", text: " · " + (r.cls || "") + " · " + fmt(r.inner_km, 0) + "–" + fmt(r.outer_km, 0) + " km" })));
      if (r.hotspots && r.hotspots.length) rr.push(el("div", { class: "pl-line pl-sub c-amber", text: "◆ " + hsText(r.hotspots) }));
      else if (!r.belt) rr.push(el("div", { class: "pl-line pl-sub c-dim", text: t("no hotspots known - map the ring with the DSS") }));
      // your prospecting in this ring, and what rings like it held at such hotspots
      // L1: the share with its 95 % range; L2: thin groups lean on broader ones
      const mats = (p) => p.mats.map(m => m.name + " " + m.share + " %"
        + (m.lo !== undefined && p.level === undefined ? " (" + m.lo + "–" + m.hi + ")" : "")).join(" · ");
      const LEVEL = { class: N_("few rocks yet - leaning on all {c} rings"), all: N_("few rocks yet - leaning on all your rings") };
      if (r.prospect) rr.push(el("div", { class: "pl-line pl-sub small" + (r.prospect.thin ? " c-dim" : "") },
        el("span", { class: "c-green", text: "⛏ " + t("your rocks here ({n}):", { n: r.prospect.rocks }) + " " }), mats(r.prospect),
        r.prospect.motherlodes.length ? el("span", { class: "c-violet", text: " · ◆ " + r.prospect.motherlodes.map(([m, n]) => m + " ×" + n).join(", ") }) : null));
      for (const e of r.expected || []) rr.push(el("div", { class: "pl-line pl-sub small c-dim" },
        el("span", { text: "↳ " + t("at {h} hotspots ({r} rings, {n} rocks) also:", { h: e.hotspot, r: e.rings, n: e.rocks }) + " " }),
        el("span", { text: mats(e) }),
        e.level && e.level !== "hotspot" ? el("span", { class: "c-amber", text: " · " + t(LEVEL[e.level], { c: r.cls || "" }) }) : null));
    }
    const loose = b.hotspots.filter(h => !ringNames.has(h.ring));
    if (loose.length) rr.push(el("div", { class: "pl-line c-amber", text: "◆ " + hsText(loose) }));
    if (b.rings.some(r => r.prospect || (r.expected && r.expected.length)))
      rr.push(el("div", { class: "c-dim small", text: t("Share of prospected rocks that held the material - from your own prospector reports.") }));
    right.push(frame(t("RINGS"), b.reserve ? t("reserves: {r}", { r: b.reserve }) : "", rr));
  }

  // ground mining with the Rhino: what rigs yielded here, and on bodies of this class
  if (b.ground) {
    const g = b.ground, gl = [];
    if (g.here) gl.push(el("div", { class: "pl-line" }, el("span", { class: "c-green", text: "⛏ " + t("here: {n} rigs, {t} t", { n: g.here.rigs, t: g.here.tonnes }) + " · " }),
      g.here.mats.map(m => m.name + " " + m.t + " t").join(" · ")));
    if (g.expected) gl.push(el("div", { class: "pl-line small c-dim" },
      el("span", { text: "↳ " + t("on other {c} ({n} bodies):", { c: g.expected.cls, n: g.expected.bodies }) + " " }),
      el("span", { text: g.expected.mats.map(m => m.name + " " + m.t + " t").join(" · ") })));
    gl.push(el("div", { class: "c-dim small", text: t("From the rigs you collected with the Rhino.") }));
    right.push(frame(t("GROUND MINING"), "", gl));
  }

  if (b.signals && b.signals.length) {
    const ss = b.signals.map(s => el("div", { class: "pl-line c-" + s.tone, text: "◆ " + s.label + (s.count > 1 ? " ×" + s.count : "") }));
    if (b.signals.some(s => s.kind && s.kind.startsWith("site:")))
      ss.push(el("div", { class: "c-dim small", text: t("“from pickup”: a surface site recognised by the material collected – the journal does not report it itself.") }));
    left.push(frame(t("SIGNALS"), b.signals.length + "", ss, { kind: b.signals.some(s => s.tone === "violet") ? "disc" : "" }));
  }
  if (b.materials_found && b.materials_found.length) {
    const mf = b.materials_found.map(m => el("div", { class: "pl-line" },
      el("span", { class: "c-green", text: m.label + " ×" + m.count }),
      el("span", { class: "c-dim", text: " · " + (m.category || "") + " · " + (m.last || "") })));
    right.push(frame(t("COLLECTED HERE"), b.materials_found.length + "", mf));
  }

  root.append(el("div", { class: "pl-grid" }, el("div", { class: "pl-col" }, ...left), el("div", { class: "pl-col" }, ...right)));
  countUp(root);
}
