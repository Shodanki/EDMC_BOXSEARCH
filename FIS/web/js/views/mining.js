// MINING – everything about mining in one place. Tritium first (deep space:
// the carrier's fuel), then goods to sell (what pays the carrier's upkeep).
// Left: the session (live or the last one), tritium for the carrier, the
// mining ships. Right: ring hotspots nearby, goods and income, all sessions.

import { getJSON } from "../api.js";
import { el, frame, fmt, withPopout } from "../ui.js";
import { t, N_ } from "../i18n.js";

const CONTENT = { low: N_("low"), medium: N_("medium"), high: N_("high") };
const VERDICT = { good: N_("good rock"), fair: N_("fair"), poor: N_("poor - move on") };
let root = null, data = null, busy = false, live = null, liveBusy = false, liveBox = null;
let material = localStorage.getItem("fis.mine.material") || "tritium";

export function mount(r) {
  root = r;
  root.classList.add("mine-view");
  window.addEventListener("fis-layout", () => { if (data) render(); });
}

export async function update(ctx, reason) {
  if (!root) return;
  if (reason === "live") { if (data) await updateLive(); return; }   // Status.json: cheap, often
  if (busy) return;
  busy = true;
  try { data = await getJSON("/api/mining"); } catch (e) { data = null; }
  try { live = await getJSON("/api/mining/live"); } catch (e) { live = null; }
  busy = false;
  render();
}

async function updateLive() {
  if (liveBusy) return;
  liveBusy = true;
  try { live = await getJSON("/api/mining/live"); } catch (e) { /* keep the last */ }
  liveBusy = false;
  if (liveBox) { const n = liveStatus(); liveBox.replaceWith(n); liveBox = n; }
}

function stamp(ts) {
  return ts ? new Date(ts * 1000).toLocaleString(undefined, { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
}
function age(s) {
  if (s === null || s === undefined) return "?";
  return s < 3600 ? t("{n} min ago", { n: Math.max(1, Math.round(s / 60)) }) : s < 172800 ? t("{n} h ago", { n: Math.round(s / 3600) })
    : t("{n} days ago", { n: Math.round(s / 86400) });
}
function cr(v) { return v === null || v === undefined ? "–" : Math.abs(v) >= 1e6 ? fmt(v / 1e6, 1) + " M Cr" : fmt(v, 0) + " Cr"; }
function row(k, ...v) { return el("div", { class: "ns-row" }, el("div", { class: "ns-k", text: k }), el("div", { class: "ns-v" }, ...v)); }
function detail(id) {
  if (!id) return;
  const w = window.open(location.pathname + "?solo=tactical&system=" + id, "fis-detail", "popup,width=1280,height=860");
  if (w) w.focus();
}

function render() {
  if (!root) return;
  root.replaceChildren();
  if (!data) { root.append(frame(t("MINING"), "", el("div", { class: "empty", text: t("no data yet") }))); return; }
  root.append(el("div", { class: "mine-grid" },
    el("div", { class: "mine-col" }, withPopout(liveBox = liveStatus(), "mining"), session(), limpets(), ships()),
    el("div", { class: "mine-col" }, tritium(), hotspots(), goods(), history())));
}

// ------------------------------------------------------------ live status
// two bars: the hold (limpets | goods | free, with the advised limpet load
// marked) and the refining of the last 10 minutes (one tick per tonne - the
// game writes nothing about the refinery's bins, only each finished tonne)
const GOOD_COL = ["#7CFF6B", "#FFB23E", "#B57CFF", "#4FA3FF", "#E8A06A"];
function liveStatus() {
  const L = live;
  if (!L || !L.capacity) return frame(t("MINING STATUS"), "", el("div", { class: "c-dim", text: t("no data yet") }), { appear: false });
  const cap = L.capacity, pct = (n) => (100 * n / cap).toFixed(2) + "%";
  const segs = [el("i", { class: "mh-limpets", style: { width: pct(L.limpets) }, title: t("Limpets") + " " + L.limpets })];
  L.goods.forEach((g, i) => segs.push(el("i", { style: { width: pct(g.count), background: GOOD_COL[i % GOOD_COL.length] }, title: g.name + " " + g.count + " t" })));
  const hold = el("div", { class: "mh-bar" }, ...segs,
    L.advice ? el("b", { class: "mh-mark", style: { left: pct(L.advice.limpets) }, title: t("advised: {n} limpets", { n: L.advice.limpets }) }) : null);
  const legend = el("div", { class: "mh-legend small" },
    el("span", { class: "c-cyan", text: "■ " + t("Limpets") + " " + L.limpets }),
    ...L.goods.map((g, i) => el("span", { style: { color: GOOD_COL[i % GOOD_COL.length] }, text: "■ " + g.name + " " + g.count + " t" })),
    el("span", { class: "c-dim", text: "□ " + t("free") + " " + fmt(L.free, 0) + " / " + fmt(cap, 0) + " t" }));
  const ticks = el("div", { class: "mh-bar mh-ticks", title: t("each tonne refined in the last 10 minutes") },
    ...(L.ticks || []).map(s => el("b", { style: { left: (100 - 100 * s / 600).toFixed(2) + "%" } })));
  const rows = [
    el("div", { class: "mh-row" }, el("span", { class: "c-dim", text: t("Hold") }), hold), legend,
    el("div", { class: "mh-row" }, el("span", { class: "c-dim", text: t("Refined") }), ticks),
    el("div", { class: "mh-legend small" }, el("span", { class: "c-dim", text: "−10 min" }),
      el("span", { class: L.rate_h ? "c-green" : "c-dim", text: L.rate_h ? t("{r} t/h now", { r: fmt(L.rate_h, 0) }) : t("nothing refined in 10 min") }),
      el("span", { class: "c-dim", text: t("now") })),
  ];
  if (L.target_name) rows.push(el("div", { class: "small", text: t("Target") + ": " + L.target_name }));
  // how far cargo space and limpets go
  const est = [];
  if (L.full_in_min !== undefined) est.push(t("full in ~{m} min at this rate", { m: fmt(L.full_in_min, 0) }));
  const short = L.limpets_for_t !== null && L.limpets_for_t !== undefined && L.room_t !== undefined && L.limpets_for_t < L.room_t;
  if (L.room_t !== undefined)
    est.push(short ? t("limpets last for ~{t} t - room for {f} t", { t: fmt(L.limpets_for_t, 0), f: fmt(L.room_t, 0) })
      : t("room for ~{f} t, limpets last for ~{t} t - enough", { f: fmt(L.room_t, 0), t: fmt(L.limpets_for_t, 0) }));
  if (est.length) rows.push(el("div", { class: "small " + (short ? "c-amber" : "c-dim"), text: est.join(" · ") }));
  // prospector reports: the last one large, a few before it
  const rocks = L.rocks || [];
  if (rocks.length) {
    const r = rocks[0], key = L.key;
    rows.push(el("div", { class: "sr-h", text: t("Prospector") + " · " + (r.ago < 90 ? t("{s} s ago", { s: r.ago }) : t("{n} min ago", { n: Math.round(r.ago / 60) })) }));
    rows.push(el("div", { class: "pr-rock" }, ...r.materials.map(m => el("div", { class: "pr-mat" + (m.key === key ? " key" : "") },
      el("span", { text: m.name }), el("span", { class: "lbar" }, el("i", { style: { width: Math.min(100, m.pct * 2) + "%" } })),
      el("span", { class: "num", text: fmt(m.pct, 1) + " %" })))));
    rows.push(el("div", { class: "small " + (r.verdict === "good" ? "c-green" : r.verdict === "poor" ? "c-amber" : ""),
      text: [r.content ? t(CONTENT[r.content]) : "", r.motherlode ? "◆ " + t("motherlode") + ": " + r.motherlode : "",
        r.remaining < 100 ? t("{r} % left", { r: fmt(r.remaining, 0) }) : "",
        r.verdict ? t(VERDICT[r.verdict]) + (L.best_share ? " (" + t("best {b} %", { b: fmt(L.best_share, 1) }) + ")" : "") : ""].filter(Boolean).join(" · ") }));
    if (rocks.length > 1) rows.push(el("div", { class: "pr-list small c-dim" }, ...rocks.slice(1).map(x =>
      el("div", { class: x.verdict === "good" ? "c-green" : "", text: fmt(Math.round(x.ago / 60), 0) + " min · " + (key ? fmt(x.share, 1) + " % " : "")
        + (x.content ? t(CONTENT[x.content]) : "") + (x.motherlode ? " · ◆ " + x.motherlode : "") }))));
  }
  return frame(t("MINING STATUS"), L.active ? t("live") + " · " + (L.ship || "") : (L.ship || ""), rows, { cls: "mine-live", appear: false });
}

// ------------------------------------------------------------ session
function session() {
  const m = data.session;
  if (!m) return frame(t("MINING"), "", el("div", { class: "c-dim", text: t("No mining in the journals yet.") }), { appear: false });
  const rock = (a) => a.materials.slice(0, 3).map(x => x.name + " " + fmt(x.pct, 1) + " %").join(" · ")
    + (a.content ? " · " + t(CONTENT[a.content]) : "") + (a.motherlode ? " · ◆ " + a.motherlode : "");
  // M2: ground mining (SRV Rhino) has no limpets and no asteroids
  const ground = m.kind === "ground";
  return frame(t("MINING"), (ground ? t("ground · {v}", { v: m.vehicle || "SRV" }) + " · " : "") + (m.active ? t("active") : stamp(m.end)), [
    el("div", { class: "gal-big" }, el("span", { class: "c-cyan", text: fmt(m.total, 0) + " t" }),
      el("span", { class: "c-dim", text: "  " + t("{h} t/h · {m} per minute · {n} min", { h: fmt(m.per_hour, 1), m: fmt(m.per_min, 2), n: m.minutes }) })),
    ...m.refined.map(r => el("div", { class: "cg" }, el("span", { text: r.name }),
      el("span", { class: "num", text: fmt(r.count, 0) + " t · " + fmt(r.per_hour, 1) + " t/h" }))),
    ground ? el("div", { class: "small c-dim", text: t("Ground mining from the surface vehicle - no limpets; not counted in the limpet advice.") }) : null,
    ground ? null : el("div", { class: "small", text: t("Limpets: {p} prospector · {c} collector launched · {l} on board",
      { p: m.drones.prospector, c: m.drones.collection, l: data.limpets }) }),
    ground ? null : el("div", { class: "small c-dim", text: t("{n} asteroids prospected · {ml} motherlodes · {c} cracked",
      { n: m.asteroids, ml: m.motherlodes, c: m.cracked }) }),
    m.last ? el("div", { class: "small", text: t("Last rock") + ": " + rock(m.last)
      + (m.last.remaining !== null && m.last.remaining !== undefined && m.last.remaining < 100 ? " · " + t("{r} % left", { r: fmt(m.last.remaining, 0) }) : "") }) : null,
    m.best ? el("div", { class: "small c-green", text: t("Best rock") + ": " + rock(m.best) }) : null,
    m.carrier_jumps ? el("div", { class: "small c-amber", text: t("Tritium mined: ≈ {j} carrier jumps of 500 ly", { j: fmt(m.carrier_jumps, 1) }) }) : null,
  ], { appear: false });
}

// ------------------------------------------------------------ limpet load
// cargo = limpets + ore; your sessions say how many limpets a tonne takes
function limpets() {
  const P = data.limpet_plan;
  if (!P || !P.ships.length) return null;
  const a = P.ratio.all;
  const basis = a ? t("Your sessions: {r} limpets per refined tonne ({n} sessions, {t} t) · per rock {p} prospector, {c} collector, {tr} t",
    { r: fmt(a.ratio, 2), n: a.sessions, t: fmt(a.tonnes, 0), p: fmt(a.per_rock_prospector, 1), c: fmt(a.per_rock_collector, 1), tr: fmt(a.tonnes_per_rock, 1) })
    : t("No mining session yet - assumed {r} limpets per tonne.", { r: fmt(P.default, 2) });
  const rows = P.ships.map(s => el("tr", { class: s.current ? "c-cyan" : "" },
    el("td", { text: s.name + (s.current ? " ◂" : "") }), el("td", { class: "num", text: fmt(s.cargo, 0) + " t" }),
    el("td", { class: "num c-amber", text: fmt(s.limpets, 0) }), el("td", { class: "num", text: fmt(s.ore, 0) + " t" }),
    el("td", { class: "num c-dim", text: fmt(s.ratio, 2) + (s.own ? "" : " *") })));
  const cur = P.ships.find(s => s.current);
  return frame(t("LIMPET LOAD"), "", [
    el("table", { class: "mine-table" },
      el("tr", {}, ...[t("Ship"), t("Cargo"), t("Limpets"), t("Ore"), t("per t")].map(h => el("th", { text: h }))), ...rows),
    cur ? el("div", { class: "small " + (Math.abs(cur.diff) <= 2 ? "c-green" : "c-amber"),
      text: t("On board {h}", { h: cur.on_board }) + " · " + (Math.abs(cur.diff) <= 2 ? t("about right")
        : cur.diff > 0 ? t("take {n} more", { n: cur.diff }) : t("{n} too many - room for ore", { n: -cur.diff })) }) : null,
    el("div", { class: "c-dim small", text: basis }),
    el("div", { class: "c-dim small", text: t("Limpets = r × cargo + {p} % reserve: every limpet launched frees its tonne, so the hold can end full of ore. Ore = what the hold holds at the end. * no session with this hull - your average.",
      { p: Math.round(P.reserve * 100) }) }),
  ], { appear: false });
}

// ------------------------------------------------------------ tritium -> carrier
function tritium() {
  const tr = data.tritium;
  if (tr.tank === undefined) return null;
  const pct = Math.round(100 * tr.tank / tr.tank_max);
  return frame(t("TRITIUM → CARRIER"), pct + " %", [
    el("div", { class: "lg-row" }, el("span", { class: "c-dim", text: t("Tank") }),
      el("span", { class: "lbar " + (pct < 25 ? "warn" : "") }, el("i", { style: { width: pct + "%" } })),
      el("span", { text: fmt(tr.tank, 0) + " / " + fmt(tr.tank_max, 0) + " t" })),
    row(t("Range"), el("span", { class: "c-green", text: fmt(tr.range.ly, 0) + " ly" }),
      el("span", { class: "c-dim", text: "  " + t("{n} full jumps of 500 ly", { n: tr.range.jumps }) })),
    row(t("Per 500 ly"), fmt(tr.per_jump, 0) + " t"),
    row(t("To a full tank"), fmt(tr.to_full, 0) + " t"),
    row(t("In your ship"), fmt(tr.ship, 0) + " t",
      tr.with_ship ? el("span", { class: "c-dim", text: "  → " + t("tank filled: {ly} ly", { ly: fmt(tr.with_ship.ly, 0) }) }) : null),
    tr.mined ? row(tr.mined.active ? t("Mining now") : t("Last mining"),
      el("span", { class: "c-green", text: "+" + fmt(tr.mined.t, 0) + " t" }),
      el("span", { class: "c-dim", text: "  ≈ " + t("{j} jumps · {ly} ly", { j: fmt(tr.mined.jumps, 1), ly: fmt(tr.mined.ly, 0) }) })) : null,
    row(t("Delivered"), t("{a} t into the hold · {d} t into the tank (30 days: {a30} t · {d30} t)", {
      a: fmt(tr.to_carrier.all, 0), d: fmt(tr.deposited.all, 0), a30: fmt(tr.to_carrier["30d"], 0), d30: fmt(tr.deposited["30d"], 0) })),
    tr.hold ? row(t("In the carrier's hold"), fmt(tr.hold.t, 0) + " t",
      tr.with_hold ? el("span", { class: "c-green", text: "  → " + t("with it: {ly} ly · {n} jumps", { ly: fmt(tr.with_hold.ly, 0), n: tr.with_hold.jumps }) }) : null,
      el("span", { class: "c-dim small", text: "  " + t("Frontier data, {a}", { a: age(tr.hold.age_s) }) }))
      : el("div", { class: "c-dim small", text: t("Tritium in the carrier's hold comes with EDMC's Frontier data (Companion API) - none yet.") }),
  ], { appear: false });
}

// ------------------------------------------------------------ ships
function ships() {
  if (!data.ships.length) return null;
  const dots = (n) => "●".repeat(n) + "○".repeat(5 - n);
  return frame(t("MINING SHIPS"), String(data.ships.length), data.ships.map(s => el("div", { class: "cg" },
    el("span", { text: (s.name || s.type) + (s.ident ? " · " + s.ident : "") + (s.current ? " ◂" : "") }),
    el("span", { class: "num", text: dots(s.rating) + "  " + fmt(s.cargo, 0) + " t · " + (s.location || "?") }))), { appear: false });
}

// ------------------------------------------------------------ hotspots
function hotspots() {
  const all = data.hotspots;
  const kinds = [...new Map(all.map(h => [h.key, h.material])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const sel = el("select", { class: "lay-pick", onchange: (e) => { material = e.target.value; localStorage.setItem("fis.mine.material", material); render(); } },
    el("option", { value: "", text: t("all") }), ...kinds.map(([k, n]) => el("option", { value: k, text: n })));
  sel.value = kinds.some(([k]) => k === material) ? material : "";
  const list = all.filter(h => !sel.value || h.key === sel.value).slice(0, 14);
  return frame(t("RING HOTSPOTS"), data.from ? t("from {s}", { s: data.from }) : "", [
    el("div", { class: "gal-row" }, el("span", { class: "c-dim", text: t("Material") }), sel),
    list.length ? el("div", { class: "mine-list" }, ...list.map(h => el("div", { class: "cg mine-hs", title: h.system, onclick: () => detail(h.id) },
      el("span", { text: h.ring + (h.count > 1 ? "  ×" + h.count : "") + (sel.value ? "" : " · " + h.material) }),
      el("span", { class: "num", text: h.ly === null ? "?" : h.ly < 0.1 ? t("here") : fmt(h.ly, 1) + " ly" }))))
      : el("div", { class: "c-dim", text: t("No hotspots known for this material - scan rings with the DSS.") }),
    el("div", { class: "c-dim small", text: t("Rings you mapped (plugin database). A click opens the system.") }),
  ], { appear: false });
}

// ------------------------------------------------------------ goods and income
function goods() {
  const inc = data.income;
  const rows = data.goods.map(g => el("tr", {},
    el("td", { text: g.name }), el("td", { class: "num", text: fmt(g.refined, 0) }), el("td", { class: "num", text: fmt(g.refined_30d, 0) }),
    el("td", { class: "num", text: fmt(g.sold, 0) }), el("td", { class: "num", text: cr(g.revenue) }),
    el("td", { class: "num", text: g.avg_price ? fmt(g.avg_price, 0) : "–" })));
  const table = el("table", { class: "mine-table" },
    el("tr", {}, ...[t("Good"), t("mined t"), t("30 days"), t("sold t"), t("earned"), t("Cr/t")].map(h => el("th", { text: h }))), ...rows);
  return frame(t("GOODS & INCOME"), "", [
    table,
    el("div", { class: "small " + (inc.covers_pct >= 100 ? "c-green" : "c-amber"), text: t("Sold in 30 days: {r} ≈ {w} per week", { r: cr(inc.revenue_30d), w: cr(inc.per_week) })
      + (inc.upkeep_per_week ? " · " + t("{p} % of the carrier's upkeep ({u} per week)", { p: inc.covers_pct, u: cr(inc.upkeep_per_week) }) : "") }),
    el("div", { class: "c-dim small", text: t("Sales to your own carrier are not income - they fill its hold.") }),
  ], { appear: false });
}

// ------------------------------------------------------------ sessions
function history() {
  if (!data.sessions.length) return null;
  return frame(t("SESSIONS"), String(data.sessions.length), el("table", { class: "mine-table" },
    el("tr", {}, ...[t("Date"), "min", t("Good"), "t", "t/h"].map(h => el("th", { text: h }))),
    ...data.sessions.map(s => el("tr", { class: s.active ? "c-cyan" : "" },
      el("td", { text: stamp(s.start) }), el("td", { class: "num", text: fmt(s.minutes, 0) }),
      el("td", { text: (s.main_name || "–") + (s.kind === "ground" ? " · " + (s.vehicle || "SRV") : "") }), el("td", { class: "num", text: fmt(s.total, 0) }),
      el("td", { class: "num", text: fmt(s.per_hour, 0) })))), { appear: false });
}
