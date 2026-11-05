// PLANET – datasheet of one body.

import { getJSON } from "../api.js";
import { el, frame, fmt, num, chip, hbar, tile, countUp, classDe } from "../ui.js";
import { t, N_, lang } from "../i18n.js";

let root = null;
let current = null;     // datasheet JSON
let loading = null;

export function mount(r) { root = r; root.classList.add("planet-view"); }

export async function load(ctx) {
  const sel = ctx.store.selected;
  if (!sel) { current = null; render(ctx); return; }
  const key = sel.id64 + "/" + sel.body_id;
  loading = key;
  const data = await getJSON("/api/body/" + key);
  if (loading !== key) return;           // a newer selection won
  current = data;
  if (root && ctx.store.view === "planet") render(ctx);
}

export function update(ctx, reason) {
  if (!root) return;
  if (!ctx.store.selected && ctx.store.system && ctx.store.system.route && ctx.store.system.route.next) {
    // nothing picked yet: show the next stop of the route
    const leg = ctx.store.system.route.legs[ctx.store.system.route.next - 1];
    if (leg) { ctx.store.selected = { id64: ctx.store.system.id64, body_id: leg.body_id }; load(ctx); return; }
  }
  if (reason === "show") render(ctx);
}

const ATMO = { CarbonDioxide: "CO₂", SulphurDioxide: "SO₂", Nitrogen: "N₂", Oxygen: "O₂", Water: "H₂O",
  Ammonia: "NH₃", Methane: "CH₄", Argon: "Ar", Neon: "Ne", Helium: "He", Hydrogen: "H₂", Silicates: "Silicates", Iron: "Fe" };
const atmoName = (k) => (k === "Silicates" && lang() === "de") ? "Silikate" : (ATMO[k] || k);
const COMPOSITION = { Rock: N_("Rock"), Metal: N_("Metal"), Ice: N_("Ice") };

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

  const left = [frame(t("DATASHEET"), b.kind === "Star" ? t("Star") : t("Body {n}", { n: b.body_id }), [head, tiles], { kind: "hot" })];

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
  const right = [];
  if (b.kind !== "Star") right.push(frame(t("ATMOSPHERE · SURFACE"), "", atmo));

  // biology
  const bio = [];
  if (b.bio.signals || b.bio.species.length || b.bio.prediction.length) {
    bio.push(el("div", { class: "pl-line" },
      el("span", { class: "c-amber", text: t(b.bio.signals === 1 ? "{n} bio signal" : "{n} bio signals", { n: b.bio.signals }) }),
      el("span", { class: "c-dim", text: " · " + t("{n} analysed", { n: b.bio.analysed }) })));
    if (b.bio.genera.length) bio.push(el("div", { class: "pl-line" }, el("span", { class: "c-dim", text: t("Genera (DSS)") + " " }), b.bio.genera.join(", ")));
    for (const s of b.bio.species) bio.push(el("div", { class: "pl-line c-green", text: "✓ " + (s.variant || s.species) }));
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
    const rr = b.rings.map(r => el("div", { class: "pl-line" }, el("span", { class: "c-cyan", text: (r.name || "").replace(b.name, "").trim() || "Ring" }),
      el("span", { class: "c-dim", text: " · " + (r.cls || "") + " · " + fmt(r.inner_km, 0) + "–" + fmt(r.outer_km, 0) + " km" })));
    for (const h of b.hotspots) rr.push(el("div", { class: "pl-line c-amber", text: "◆ " + h.material + " ×" + h.count }));
    right.push(frame(t("RINGS"), "", rr));
  }

  if (b.signals && b.signals.length) {
    const ss = b.signals.map(s => el("div", { class: "pl-line c-" + s.tone, text: "◆ " + s.label + (s.count > 1 ? " ×" + s.count : "") }));
    if (b.signals.some(s => s.kind && s.kind.startsWith("site:")))
      ss.push(el("div", { class: "c-dim small", text: t("“from pickup”: a surface site recognised by the material collected – the journal does not report it itself.") }));
    right.push(frame(t("SIGNALS"), b.signals.length + "", ss, { kind: b.signals.some(s => s.tone === "violet") ? "disc" : "" }));
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
