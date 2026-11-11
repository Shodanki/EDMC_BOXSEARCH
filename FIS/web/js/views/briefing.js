// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// BRIEFING – the next jump, Wing-Commander style.

import { el, frame, fmt, chip, countUp, hbar } from "../ui.js";
import { t, N_ } from "../i18n.js";

let root = null;

export function mount(r) {
  root = r;
  root.classList.add("briefing-view");
}

function row(k, ...v) {
  return el("div", { class: "br-row" }, el("div", { class: "br-k", text: k }), el("div", { class: "br-v" }, ...v));
}

// status code from the server -> headline and explanation
const STATUS = {
  only_us: [N_("ONLY KNOWN TO US"), N_("You were there, but neither EDSM, Spansh nor EDDiscovery know the system (according to the plugin database)")],
  unknown: [N_("IN NO DATABASE"), N_("Neither EDSM, Spansh nor EDDiscovery report the system (according to the plugin database) – first discovery possible")],
  // I1: say "in no database" only where a source was asked
  inhabited: [N_("INHABITED"), N_("Population or a station seen in the journal – the databases know the system")],
  unchecked: [N_("NOT CHECKED"), N_("Outside our data frame – no database was asked about this system")],
  visited: [N_("ALREADY VISITED"), N_("known in {s}")],
  known: [N_("KNOWN"), N_("known in {s}")],
};

function expectation(x) {
  if (x.key === "avg_bodies") return t("~{n} bodies (average of {k} known systems in the boxel)", { n: x.n, k: x.of });
  if (x.key === "bio_neighbours") return t("Bio: {n} of {k} visited neighbours", { n: x.n, k: x.of });
  return x.text || "";
}

let lastSig = null, lastTarget = undefined;

export function update(ctx, reason) {
  if (!root) return;
  const b = ctx.store.briefing;
  const ship = ctx.store.ship || {};
  const tg = b && b.target;
  // re-render only when something visible changed; animate only a new target
  const sig = JSON.stringify([b && { ...b, generated: 0 }, ship.jumping, ctx.store.survey]);
  if (sig === lastSig && reason !== "show") return;
  lastSig = sig;
  const tname = tg ? tg.name : null;
  const appear = reason === "show" || tname !== lastTarget;
  lastTarget = tname;
  root.replaceChildren();
  const ap = approach(b && b.approach, appear);
  if (ap) root.append(ap);
  if (!tg) {
    root.append(frame("BRIEFING", t("no target"),
      el("div", { class: "empty" },
        t("NO JUMP TARGET SET"), el("br"),
        el("span", { class: "c-dim", text: t("Pick a target in the galaxy map – the briefing appears by itself.") })),
      { cls: "br-main", appear }));
    const ch0 = carriersTile(b && b.carriers_here, appear);
    if (ch0) root.append(ch0);
    if (b && b.navroute && b.navroute.length) root.append(navList(b.navroute, null, appear));
    const sv0 = surveyTile(ctx.store.survey, appear);
    if (sv0) root.append(sv0);
    return;
  }
  const unknown = b.status === "unknown" || b.status === "only_us";
  const st = STATUS[b.status] || [b.status || "", ""];
  const known = (tg.known_sources || []).join(", ");
  const np = tg.navpoint ? "NAVPOINT " + tg.navpoint[0] + "/" + tg.navpoint[1] : (tg.source || "");
  const star = tg.star_class
    ? [el("span", { class: "c-cyan", text: tg.star_class }), " · ",
       tg.scoopable ? el("span", { class: "c-green", text: t("scoopable") }) : el("span", { class: "c-amber", text: t("NOT scoopable") }),
       tg.boost ? el("span", { class: "c-violet", text: " · ⚡ " + (tg.boost === "neutron" ? t("neutron star: FSD boost ×4 in the jet cone")
         : t("white dwarf: FSD boost ×1.5 in the jet cone")) }) : null]
    : [el("span", { class: "c-dim", text: t("unknown (only at StartJump)") })];
  const statusEl = el("div", {},
    el("div", { class: unknown ? "br-status disc" : "br-status", text: (unknown ? "■ " : "") + t(st[0]) }),
    el("div", { class: "c-dim", text: st[1] ? t(st[1], { s: known }) : "" }),
    b.status === "unknown" && tg.checked_by && tg.checked_by.length
      ? el("div", { class: "c-dim", text: t("checked: {s}", { s: tg.checked_by.join(", ") }) }) : null);
  const rows = [
    row(t("TARGET"), el("span", { class: "br-name", text: tg.name || "?" }),
      tg.distance_ly !== null && tg.distance_ly !== undefined ? el("span", { class: "br-dist" }, el("span", { class: "num", "data-count": tg.distance_ly, "data-digits": 1, text: fmt(tg.distance_ly, 1) }), el("span", { class: "unit", text: "ly" })) : null),
    row(t("STAR"), ...star),
    row("STATUS", statusEl),
  ];
  if (tg.visited) rows.push(row(t("VISITED"), el("span", { class: "c-dim", text: t("You have been there") + (tg.body_count ? " · " + t("{n} bodies", { n: tg.body_count }) : "") })));
  if (b.expectation && b.expectation.length)
    rows.push(row(t("EXPECTED"), el("div", {}, ...b.expectation.map(x => el("div", { text: expectation(x) })))));
  const f = b.fuel;
  if (f) {
    const parts = [];
    const maxJumps = (n) => " · " + t("{n} max jumps", { n });
    if (f.beyond_range) {
      parts.push(el("span", { class: "c-dim", text: t("Target beyond one jump – {l}/{c} t on board", { l: fmt(f.level, 1), c: fmt(f.capacity, 0) }) }));
      if (f.jumps_left !== null && f.jumps_left !== undefined) parts.push(maxJumps(f.jumps_left));
    } else if (f.after_t !== undefined) {
      parts.push(el("span", { class: f.warning ? "c-amber" : "c-green", text: t("after the jump {a}/{c} t", { a: fmt(f.after_t, 1), c: fmt(f.capacity, 0) }) }));
      if (f.jumps_after !== null && f.jumps_after !== undefined) parts.push(maxJumps(f.jumps_after));
      if (f.cost_t !== undefined) parts.push(el("span", { class: "c-dim", text: "  (" + t("uses ~{c} t", { c: fmt(f.cost_t, 2) }) + ")" }));
    } else {
      parts.push(fmt(f.level, 1) + "/" + fmt(f.capacity, 0) + " t");
      if (f.jumps_left !== null && f.jumps_left !== undefined) parts.push(maxJumps(f.jumps_left));
    }
    if (f.warning) parts.push(el("div", { class: "c-red", text: f.warning }));
    else if (f.scoop_at_target) parts.push(el("span", { class: "c-green", text: " · " + t("refuel at the target") }));
    rows.push(row(t("FUEL"), ...parts));
  }
  const bx = b.boxel;
  if (bx) {
    const bits = [el("span", { class: "c-cyan", text: bx.key }), " · " + bx.size_ly + " ly"];
    if (bx.complete) bits.push(" · ", chip(t("closed"), "mapped"));
    else if (bx.candidates_open !== null && bx.candidates_open !== undefined)
      bits.push(" · ", el("span", { class: bx.candidates_open ? "c-amber" : "c-dim", text: t("{n} candidates open", { n: bx.candidates_open }) }));
    else bits.push(el("span", { class: "c-dim", text: " · " + t("boxel not measured yet") }));
    bits.push(el("div", { class: "c-dim", text: t("{k} known · {v} visited · {a} checked as non-existent", { k: bx.known, v: bx.visited, a: bx.absent }) }));
    rows.push(row("BOXEL", ...bits));
  }
  if (b.signals && b.signals.length) {
    const parts = b.signals.slice(0, 6).map(s => el("div", { class: "c-" + s.tone,
      text: "◆ " + s.label + (s.bodies > 1 ? " · " + t("{n} bodies", { n: s.bodies }) : "") + (s.total > s.bodies ? " · ×" + s.total : "") }));
    rows.push(row(t("SIGNALS"), el("div", {}, ...parts)));
  }
  if (b.materials_found && b.materials_found.length)
    rows.push(row(t("COLLECTED"), el("div", {}, ...b.materials_found.slice(0, 4).map(m =>
      el("div", { class: "c-green", text: m.label + " ×" + m.count + (m.body ? " · " + m.body.replace((tg.name || "") + " ", "") : "") })))));
  const sp = b.sphere;
  if (sp) rows.push(row(t("SPHERE"), sp.inside
    ? el("span", { class: "c-green", text: t("inside the sphere") })
    : el("span", { class: "c-amber", text: t("outside the sphere") }),
    el("span", { class: "c-dim", text: " · " + t("{d} ly from the centre (r {r})", { d: fmt(sp.from_centre_ly, 1), r: fmt(sp.radius, 0) }) })));
  if (tg.remaining_jumps) rows.push(row("ROUTE", t(tg.remaining_jumps === 1 ? "{n} jump to the target" : "{n} jumps to the target", { n: tg.remaining_jumps })));
  if (ship.jumping) rows.push(row(t("JUMP"), el("span", { class: "c-amber blink", text: t("FSD ACTIVE") + " ⟫ " + (ship.jumping.name || "") })));

  root.append(frame("BRIEFING", np, el("div", { class: "br-rows" }, ...rows),
    { kind: unknown ? "disc" : "hot", cls: "br-main", appear }));
  const ch = carriersTile(b.carriers_here, appear);
  if (ch) root.append(ch);
  if (b.navroute && b.navroute.length) root.append(navList(b.navroute, tg.name, appear));
  const sv = surveyTile(ctx.store.survey, appear);
  if (sv) root.append(sv);
  if (appear) countUp(root);
}

// B1: your own and favourite carriers known in this system - with where that
// comes from and how old it is (never a live position)
const CAR_HOW = { location: N_("your journal"), expected: N_("your journal – jump time passed"),
  docked: N_("docked there"), sighted: N_("seen in the FSS"), jump: N_("jumped with you aboard"),
  spansh: N_("Spansh lookup") };
function carAge(s) {
  if (s === null || s === undefined) return "?";
  return s < 3600 ? t("{n} min ago", { n: Math.max(1, Math.round(s / 60)) }) : s < 172800 ? t("{n} h ago", { n: Math.round(s / 3600) })
    : t("{n} days ago", { n: Math.round(s / 86400) });
}
function carriersTile(list, appear) {
  if (!list || !list.length) return null;
  const rows = list.map((c) => el("div", { class: "br-car" },
    el("span", { class: c.kind === "own" ? "c-amber" : "c-cyan", text: (c.kind === "own" ? "◆ " : "★ ") + [c.name, c.callsign].filter(Boolean).join(" ") }),
    el("span", { class: "c-dim", text: " · " + (c.kind === "own" ? t("your carrier") : t("favourite")) + " · "
      + t(CAR_HOW[c.how] || "your journal") + (c.source === "stored" ? " (" + t("stored") + ")" : "") + " · " + carAge(c.age_s) }),
    c.note ? el("div", { class: "small c-dim", text: c.note }) : null));
  return frame(t("CARRIERS HERE"), t("last known"), el("div", {}, ...rows), { cls: "br-carriers", appear });
}

// Sphere progress (/api/survey) – a small tile beside the briefing.
// near a body: what you already know there (finds, open species, the SRV)
const FIND_ICON = { codex: "★", settlement: "⌂", screenshot: "◉", material: "■" };
function approach(a, appear) {
  if (!a) return null;
  const rows = [];
  const facts = [];
  if (a.gravity_g) facts.push(fmt(a.gravity_g, 2) + " g");
  if (a.bio) facts.push("Bio ×" + a.bio + (a.analysed ? " (" + a.analysed + " ✓)" : ""));
  if (a.geo) facts.push("Geo ×" + a.geo);
  if (facts.length) rows.push(el("div", { class: "c-dim", text: facts.join(" · ") }));
  if (a.parked) rows.push(el("div", { class: "c-amber", text: "◆ " + t("your SRV is parked here") }));
  for (const s of a.species) rows.push(el("div", { class: "c-amber", text: "◐ " + s.species + " " + s.samples + "/3" }));
  for (const f of a.finds) rows.push(el("div", {}, el("span", { class: "c-cyan", text: (FIND_ICON[f.kind] || "·") + " " }), f.label || f.kind));
  return frame(t("APPROACH"), a.short || a.body, rows, { cls: "br-approach", appear });
}

function surveyTile(s, appear) {
  if (!s || !s.center || !s.systems) return null;
  const n = s.systems;
  const body = [
    el("div", { class: "sv-head" },
      el("span", { class: "c-cyan", text: s.start_system || "?" }),
      el("span", { class: "c-dim", text: " · r " + fmt(s.radius, 0) + " ly" + (s.masscodes ? " · " + t("mass") + " " + s.masscodes.split(",").map((c) => "abcdefgh"[+c] || c).join("") : "") })),
    hbar(t("VISITED"), n.visited, Math.max(1, n.known), n.visited + "/" + n.known + (n.pct_visited !== null && n.pct_visited !== undefined ? " · " + fmt(n.pct_visited, 1) + " %" : "")),
    hbar("FSS ✓", n.fss_complete, Math.max(1, n.known), n.fss_complete + "/" + n.known),
  ];
  if (s.boxels && s.boxels.total)
    body.push(hbar("BOXEL ✓", s.boxels.complete, s.boxels.total, s.boxels.complete + "/" + s.boxels.total));
  const extra = [];
  if (n.only_us) extra.push(el("span", { class: "c-violet", text: t("{n} only known to us", { n: n.only_us }) }));
  if (s.carrier && s.carrier.system) extra.push(el("span", { class: "c-dim", text: "Carrier " + (s.carrier.callsign || s.carrier.name || "") + " · " + s.carrier.system }));
  if (extra.length) body.push(el("div", { class: "sv-extra" }, ...extra));
  const tag = s.active ? t("active") : t("resting");
  return frame(t("SPHERE"), tag, el("div", { class: "sv-body" }, ...body), { cls: "br-survey", appear });
}

// I1: a hop no database reports - unknown only where someone was asked
function levelTag(level) {
  if (level === "unchecked") return el("span", { class: "c-dim", text: t("not checked"), title: t("Outside our data frame – no database was asked about this system") });
  if (level === "inhabited") return el("span", { class: "c-dim", text: t("inhabited") });
  return chip(t("unknown"), "first");
}

function navList(hops, target, appear) {
  const list = el("ol", { class: "navlist" });
  for (const h of hops) {
    const unknown = !(h.known_sources && h.known_sources.length);
    list.append(el("li", { class: h.name === target ? "cur" : "" },
      el("span", { class: "nl-n", text: String(h.n).padStart(2, "0") }),
      el("span", { class: "nl-name", text: h.name }),
      el("span", { class: "nl-star " + (h.boost ? "c-violet" : h.scoopable === false ? "c-amber" : "c-cyan"),
        text: (h.star_class || "?") + (h.boost ? " ⚡" : ""), title: h.boost ? t("jet cone: FSD boost") : "" }),
      el("span", { class: "nl-ly", text: h.jump_ly ? fmt(h.jump_ly, 1) + " ly" : "" }),
      unknown ? levelTag(h.level) : (h.visited ? chip(t("visited"), "mapped") : el("span", { class: "c-dim", text: h.known_sources.join(" ") }))));
  }
  return frame("NAVPOINTS", t("{n} jumps plotted", { n: hops.length }), el("div", { class: "scroll" }, list), { cls: "br-nav", appear });
}
