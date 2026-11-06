// Scene preparation shared by the 3D view and the 2D fallback:
// scaling (log/linear), display sizes, colours, label layout with declutter.
//
// Coordinates: the server sends light seconds in the orbital frame
// (x, y in the reference plane, z out of it). Scene space is Three.js style,
// Y up: scene = [x, z, -y].

import { fixLabel } from "../ui.js";

export const COLOURS = {
  "star-o": "#9BB0FF", "star-b": "#AABFFF", "star-a": "#CAD7FF", "star-f": "#F8F7FF",
  "star-g": "#FFF4E8", "star-k": "#FFD2A1", "star-m": "#FFB27A", "star-l": "#FF8A5C",
  "star-t": "#D8665A", "star-y": "#A8524E", "star-x": "#FFFFFF", "star-remnant": "#E6F0FF",
  elw: "#4FA3FF", water: "#3E7BFF", ammonia: "#C9B25A", gas: "#D9A46A", icy: "#BFE3F2",
  metal: "#C9C3B5", rocky: "#A88C74", rockyice: "#9FB3B8", other: "#8FA3A0",
};
export const UI = { cyan: "#3EF2E0", green: "#7CFF6B", amber: "#FFB23E", red: "#FF4D4D", violet: "#B57CFF", dim: "#6E8F8B", text: "#CFEFEB" };

const len = (v) => Math.hypot(v[0], v[1], v[2]);
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const toScene = (p) => [p[0], p[2], -p[1]];

// log scale: units per decade of light seconds, by hierarchy level
const F0 = (r) => 12 * Math.log10(1 + r);               // around the arrival star
const FSTAR = (r) => 8 * Math.log10(1 + r);             // around a distant star
const FMOON = (r) => 0.9 + 2.2 * Math.log10(1 + 20 * r); // around a planet

// ring radius in planet radii; very wide rings (some reach 15 LS) are
// compressed beyond 2.5 radii so they do not swallow the whole system
function ringRatio(r) {
  return r <= 2.5 ? r : 2.5 + 2 * Math.log10(r / 2.5);
}

function warp(vec, f) {
  const r = len(vec);
  if (r < 1e-9) return [0, 0, 0];
  return mul(vec, f(r) / r);
}

/**
 * Build the scene model from /api/system/... JSON.
 * mode: "log" | "lin". Returns { bodies, byId, route, rings, extent, fix }.
 */
export function buildScene(sys, mode = "log") {
  const byId = new Map(sys.bodies.map((b) => [b.body_id, b]));
  const maxR = Math.max(1, ...sys.bodies.map((b) => len(b.pos)));
  const LIN = 60 / maxR;
  const memo = new Map();

  function levelFn(b, anchorLen, relLen) {
    const parent = byId.get(b.parent_id);
    if (parent && parent.kind === "Planet") return FMOON;
    if (anchorLen < 1e-3 || relLen > anchorLen) return F0;
    if (relLen < 50) return FMOON;
    return FSTAR;
  }

  function anchorOf(b) {
    const parent = byId.get(b.parent_id);
    if (parent) return S(parent);
    return warp(b.ppos || [0, 0, 0], F0);
  }

  function S(b) {
    if (memo.has(b.body_id)) return memo.get(b.body_id);
    memo.set(b.body_id, [0, 0, 0]);              // cycle guard
    let p;
    if (mode === "lin") p = mul(b.pos, LIN);
    else {
      const pp = b.ppos || [0, 0, 0];
      const rel = sub(b.pos, pp);
      const f = levelFn(b, len(pp), len(rel));
      // top level: warp the absolute position (log is not additive, so
      // anchor + warp(rel) would shift a binary's arrival star off the origin)
      p = f === F0 ? warp(b.pos, F0) : add(anchorOf(b), warp(rel, f));
    }
    memo.set(b.body_id, p);
    return p;
  }

  function orbitPts(b) {
    if (!b.orbit) return null;
    if (mode === "lin") return b.orbit.map((q) => toScene(mul(q, LIN)));
    const pp = b.ppos || [0, 0, 0];
    const f = levelFn(b, len(pp), len(sub(b.pos, pp)));
    if (f === F0) return b.orbit.map((q) => toScene(warp(q, F0)));
    const a = anchorOf(b);
    return b.orbit.map((q) => toScene(add(a, warp(sub(q, pp), f))));
  }

  const bodies = [];
  for (const b of sys.bodies) {
    // only stars and planets are drawn; belt clusters and barycentres have
    // no orbit of their own and would pile up on their parent
    if (b.kind !== "Star" && b.kind !== "Planet") continue;
    const rk = b.radius_km || (b.kind === "Star" ? 500000 : 2000);
    let size = Math.min(2.6, Math.max(0.28, 0.22 + 0.36 * Math.log10(1 + rk / 1000)));
    if (b.kind === "Star") size *= 1.35;
    if (mode === "lin") size *= 0.6;
    const ring = (b.rings || []).filter((r) => !r.belt && r.outer_km && b.radius_km);
    bodies.push({
      id: b.body_id, src: b, kind: b.kind, short: b.short, group: b.group, moon: b.moon,
      p: toScene(S(b)), size, colour: COLOURS[b.colour] || COLOURS.other,
      orbit: orbitPts(b),
      rings: ring.map((r) => ({ inner: size * ringRatio(r.inner_km / b.radius_km),
                                outer: size * ringRatio(r.outer_km / b.radius_km) })),
      flags: b.flags || {},
    });
  }
  const sById = new Map(bodies.map((b) => [b.id, b]));

  // route polyline: from the arrival star through the stops
  const legs = (sys.route && sys.route.legs) || [];
  const route = [];
  let prev = [0, 0, 0];
  for (const l of legs) {
    const tb = sById.get(l.body_id);
    if (!tb) continue;
    route.push({ ...l, a: prev, b: tb.p, isNext: sys.route.next === l.n });
    prev = tb.p;
  }

  // distance rings 1, 10, 100 ... LS (only those inside the system extent)
  const rings = [];
  for (let r = 10; r <= maxR * 3 && r <= 1e6; r *= 10) {
    rings.push({ ls: r, radius: mode === "lin" ? r * LIN : F0(r) });
  }
  const extent = Math.max(10, ...bodies.map((b) => len(b.p)));
  let fix = null;
  if (sys.fix && sById.get(sys.fix.body_id)) fix = { ...sys.fix, p: sById.get(sys.fix.body_id).p };
  return { bodies, byId: sById, route, rings, extent, fix, mode };
}

/** Centre and radius of a planetary group (planet + moons) in scene units. */
export function groupBounds(scene, group) {
  const m = scene.bodies.filter((b) => b.group === group);
  if (!m.length) return null;
  const c = [0, 0, 0];
  for (const b of m) for (let i = 0; i < 3; i++) c[i] += b.p[i] / m.length;
  let r = 0;
  for (const b of m) r = Math.max(r, len(sub(b.p, c)) + b.size);
  // a lone planet still gets some surroundings (its neighbours, the route line)
  return { c, r: Math.max(r, 4), n: m.length };
}

// ---------------------------------------------------------------------------
// overlay: labels with hairlines, declutter, moon groups (shared by 2D and 3D)
// ---------------------------------------------------------------------------

function overlaps(a, b) {
  return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
}

/**
 * Draw all labels on the 2D overlay canvas.
 * project(p) -> {x, y, ok, depth}; state: { selected, hover, fixAge }.
 */
export function drawOverlay(ctx2d, w, h, scene, project, state) {
  ctx2d.clearRect(0, 0, w, h);
  const dpr = window.devicePixelRatio || 1;
  ctx2d.save();
  ctx2d.scale(dpr, dpr);
  const W = w / dpr, H = h / dpr;
  const placed = [];
  const screen = new Map();
  for (const b of scene.bodies) {
    const s = project(b.p);
    if (s.ok && s.x > -50 && s.y > -50 && s.x < W + 50 && s.y < H + 50) {
      s.rad = state.radius ? state.radius(b) : 4;
      screen.set(b.id, s);
    }
  }

  // markers: first discovery (violet), bio (amber, dashed), selection
  ctx2d.lineWidth = 1;
  for (const b of scene.bodies) {
    const s = screen.get(b.id);
    if (!s) continue;
    const r = s.rad + 3;
    if (b.flags.first) {
      ctx2d.strokeStyle = UI.violet;
      ctx2d.beginPath(); ctx2d.arc(s.x, s.y, r, 0, Math.PI * 2); ctx2d.stroke();
    }
    if (b.flags.bio) {
      ctx2d.strokeStyle = b.flags.organics >= b.flags.bio ? "rgba(255,178,62,.45)" : UI.amber;
      ctx2d.setLineDash([2, 3]);
      ctx2d.beginPath(); ctx2d.arc(s.x, s.y, r + 3, 0, Math.PI * 2); ctx2d.stroke();
      ctx2d.setLineDash([]);
    }
    if (b.id === state.selected) {
      ctx2d.strokeStyle = UI.amber;
      const q = r + 7;
      for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {   // corner brackets
        ctx2d.beginPath();
        ctx2d.moveTo(s.x + sx * q, s.y + sy * (q - 5)); ctx2d.lineTo(s.x + sx * q, s.y + sy * q);
        ctx2d.lineTo(s.x + sx * (q - 5), s.y + sy * q); ctx2d.stroke();
      }
    }
  }

  // moon groups: collapse when the group fits in a few pixels
  const collapsed = new Map();   // group -> head id
  const groups = new Map();
  for (const b of scene.bodies) {
    if (!screen.has(b.id) || !b.group) continue;
    if (!groups.has(b.group)) groups.set(b.group, []);
    groups.get(b.group).push(b);
  }
  for (const [g, members] of groups) {
    if (members.length < 2) continue;
    let spread = 0;
    const s0 = screen.get(members[0].id);
    for (const m of members) { const s = screen.get(m.id); spread = Math.max(spread, Math.hypot(s.x - s0.x, s.y - s0.y)); }
    if (spread < 26) {
      const head = members.find((m) => !m.moon) || members[0];
      collapsed.set(g, { head: head.id, n: members.length - 1 });
    }
  }

  const nextLeg = scene.route.find((l) => l.isNext);
  const routeIds = new Set(scene.route.map((l) => l.body_id));
  const items = [];
  for (const b of scene.bodies) {
    const s = screen.get(b.id);
    if (!s) continue;
    const col = collapsed.get(b.group);
    if (col && col.head !== b.id && b.id !== state.selected && !(nextLeg && nextLeg.body_id === b.id)) continue;
    let pri = 10 + Math.min(9, b.size * 3);
    if (b.kind === "Star") pri = 60;
    if (routeIds.has(b.id)) pri = 50;
    if (b.flags.first || b.flags.bio) pri = Math.max(pri, 40);
    if (nextLeg && nextLeg.body_id === b.id) pri = 90;
    if (b.id === state.selected) pri = 95;
    if (b.id === state.hover) pri = 99;
    const tags = [];
    if (b.flags.first) tags.push(["◆", UI.violet]);
    if (b.flags.bio) tags.push(["BIO" + b.flags.bio, UI.amber]);
    if (b.flags.geo) tags.push(["GEO", "#E8A06A"]);
    if (b.flags.mapped) tags.push(["✓", UI.green]);
    if (b.flags.footfall) tags.push(["FF", UI.violet]);
    let text = b.short || "?";
    if (col && col.head === b.id && b.id !== state.selected) text += "  +" + col.n;
    items.push({ s, text, tags, pri, b, colour: b.id === state.selected ? UI.amber : (pri >= 90 ? UI.cyan : UI.text) });
  }
  // route leg labels at the mid point
  for (const l of scene.route) {
    const a = project(l.a), c = project(l.b);
    if (!a.ok || !c.ok) continue;
    const m = { x: (a.x + c.x) / 2, y: (a.y + c.y) / 2, ok: true };
    if (Math.hypot(a.x - c.x, a.y - c.y) < 60 && !l.isNext) continue;   // too short to label
    items.push({ s: m, text: l.label, tags: [], pri: l.isNext ? 85 : (l.done ? 15 : 30), leg: true,
                 colour: l.isNext ? UI.amber : (l.done ? UI.dim : "#8FCFC8") });
  }
  // LAST FIX
  if (scene.fix && scene.fix.p) {
    const s = project(scene.fix.p);
    if (s.ok) items.push({ s, text: fixLabel(scene.fix), tags: [], pri: 100, fix: true, colour: "#FFFFFF" });
  }
  // distance rings
  for (const r of scene.rings) {
    const s = project([r.radius, 0, 0]);
    if (s.ok) items.push({ s, text: r.ls >= 1000 ? (r.ls / 1000) + "k LS" : r.ls + " LS", tags: [], pri: 3, ring: true, colour: "#3C5755" });
  }

  // your carrier: hull with bridge beside the body it parks at (journal
  // BodyID; the main star when that body is not in the scene), and the body a
  // pending jump goes to
  const carrierAt = (bodyId) => {
    const b = (bodyId !== null && bodyId !== undefined && scene.byId.get(bodyId))
      || scene.bodies.find((x) => x.kind === "Star") || scene.bodies[0];
    const s = b && screen.get(b.id);
    return s ? { x: s.x + (s.rad || 4) + 9, y: s.y + (s.rad || 4) + 7, ok: true, rad: 6 } : null;
  };
  const hull = (p, dashed) => {
    ctx2d.save();
    ctx2d.strokeStyle = UI.amber; ctx2d.fillStyle = dashed ? "rgba(5,12,13,.5)" : "rgba(5,12,13,.9)";
    ctx2d.lineWidth = 1.4; if (dashed) ctx2d.setLineDash([2, 2]);
    ctx2d.fillRect(p.x - 8, p.y - 3, 16, 6); ctx2d.strokeRect(p.x - 8, p.y - 3, 16, 6);
    ctx2d.setLineDash([]); ctx2d.fillStyle = UI.amber; ctx2d.fillRect(p.x + 2, p.y - 7, 3, 4);
    ctx2d.restore();
  };
  if (scene.carrier) {
    const p = carrierAt(scene.carrier.body_id);
    if (p) { hull(p, scene.carrier.expected); items.push({ s: p, text: scene.carrier.name || "FC", tags: [], pri: 88, colour: UI.amber }); }
  }
  if (scene.carrierIn) {
    const p = carrierAt(scene.carrierIn.body_id);
    if (p) { hull(p, true); items.push({ s: p, text: "→ " + (scene.carrierIn.name || "FC"), tags: [], pri: 86, colour: UI.amber }); }
  }

  items.sort((a, b) => b.pri - a.pri);
  ctx2d.font = "12px " + getComputedStyle(document.body).getPropertyValue("--font-mono");
  const OFFS = [[14, -16], [14, 8], [-14, -16], [-14, 8], [0, -28], [0, 20], [26, -30], [-26, 22]];
  const budget = 140;
  let drawn = 0;
  for (const it of items) {
    if (drawn > budget) break;
    const tw = ctx2d.measureText(it.text).width + it.tags.reduce((s, t) => s + ctx2d.measureText(t[0]).width + 6, 0);
    const lh = 14;
    let spot = null;
    const rr = Math.min(120, (it.s.rad || 0));
    const offs = it.leg || it.ring ? [[0, -7], [0, 6], [8, -16], [-8, 10]]
      : OFFS.map(([dx, dy]) => [dx + Math.sign(dx) * rr * 0.75, dy + Math.sign(dy) * rr * 0.75]);
    for (const [dx, dy] of offs) {
      const x = dx >= 0 ? it.s.x + dx : it.s.x + dx - tw;
      const r = { x: x - 2, y: it.s.y + dy - 1, w: tw + 4, h: lh + 2 };
      if (it.leg || it.ring) r.x = it.s.x - tw / 2 - 2 + dx;
      if (r.x < 0 || r.y < 0 || r.x + r.w > W || r.y + r.h > H) continue;
      if (!placed.some((p) => overlaps(p, r))) { spot = r; break; }
    }
    if (!spot) {
      if (it.pri < 85) continue;     // thin out: only the important ones are forced
      spot = { x: it.s.x + 14, y: it.s.y - 16, w: tw + 4, h: lh + 2 };
    }
    placed.push(spot);
    drawn++;
    // hairline from the object to the label
    if (!it.leg && !it.ring) {
      ctx2d.strokeStyle = it.fix ? "rgba(255,255,255,.7)" : "rgba(62,242,224,.45)";
      ctx2d.lineWidth = 1;
      ctx2d.beginPath();
      const lx = spot.x + (spot.x > it.s.x ? 0 : spot.w);
      const ly = spot.y + spot.h - 1;
      ctx2d.moveTo(it.s.x, it.s.y);
      ctx2d.lineTo(lx, ly);
      ctx2d.lineTo(spot.x + (spot.x > it.s.x ? spot.w : 0), ly);
      ctx2d.stroke();
    }
    if (it.fix) {   // diamond marker: a reference, not a position
      ctx2d.strokeStyle = "#FFFFFF";
      ctx2d.beginPath();
      ctx2d.moveTo(it.s.x, it.s.y - 9); ctx2d.lineTo(it.s.x + 9, it.s.y);
      ctx2d.lineTo(it.s.x, it.s.y + 9); ctx2d.lineTo(it.s.x - 9, it.s.y); ctx2d.closePath();
      ctx2d.setLineDash([3, 3]); ctx2d.stroke(); ctx2d.setLineDash([]);
    }
    ctx2d.fillStyle = "rgba(5,8,10,.62)";
    ctx2d.fillRect(spot.x, spot.y, spot.w, spot.h - 2);
    ctx2d.fillStyle = it.colour;
    ctx2d.textBaseline = "top";
    let x = spot.x + 2;
    ctx2d.fillText(it.text, x, spot.y + 1);
    x += ctx2d.measureText(it.text).width + 6;
    for (const [t, c] of it.tags) {
      ctx2d.fillStyle = c;
      ctx2d.fillText(t, x, spot.y + 1);
      x += ctx2d.measureText(t).width + 6;
    }
  }
  ctx2d.restore();
  return screen;
}

/** Screen-space pick: nearest body within r pixels. */
export function pick(screen, scene, x, y, r = 14) {
  let best = null, bd = r;
  for (const b of scene.bodies) {
    const s = screen.get(b.id);
    if (!s) continue;
    const d = Math.hypot(s.x - x, s.y - y) - Math.min(10, (s.rad || 0));
    if (d < bd) { bd = d; best = b; }
  }
  return best;
}
