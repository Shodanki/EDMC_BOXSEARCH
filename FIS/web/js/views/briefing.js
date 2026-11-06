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
  if (!tg) {
    root.append(frame("BRIEFING", t("no target"),
      el("div", { class: "empty" },
        t("NO JUMP TARGET SET"), el("br"),
        el("span", { class: "c-dim", text: t("Pick a target in the galaxy map – the briefing appears by itself.") })),
      { cls: "br-main", appear }));
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
    el("div", { class: "c-dim", text: st[1] ? t(st[1], { s: known }) : "" }));
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
  if (b.navroute && b.navroute.length) root.append(navList(b.navroute, tg.name, appear));
  const sv = surveyTile(ctx.store.survey, appear);
  if (sv) root.append(sv);
  if (appear) countUp(root);
}

// Sphere progress (/api/survey) – a small tile beside the briefing.
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
      unknown ? chip(t("unknown"), "first") : (h.visited ? chip(t("visited"), "mapped") : el("span", { class: "c-dim", text: h.known_sources.join(" ") }))));
  }
  return frame("NAVPOINTS", t("{n} jumps plotted", { n: hops.length }), el("div", { class: "scroll" }, list), { cls: "br-nav", appear });
}
