// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// GALAXY in 3D (Three.js from the CDN, like SYSTEM). Same data as the 2D map.
// Galactic coordinates in ly: x to the right, y up (height above the galactic
// plane), z towards the core - in Three.js (x, y, -z), so that seen from
// above the core is "up" like in the 2D view.
//
// Path: line coloured by age (violet old -> cyan new), with a replay along
// the time axis. Systems: points. Boxels of the active sphere: real cubes,
// edges coloured by status. Spheres: wire globes. Carrier and plotted route:
// dashed lines. Galactic plane: faint grid at y = 0, arrows to Sol and core.
// Labels and the tooltip live on a 2D canvas over the 3D one.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const CORE = [25.21875, -20.90625, 25899.96875];      // Sagittarius A*
const P = (o) => new THREE.Vector3(o.x, o.y, -o.z);
const COL = { violet: 0xB57CFF, cyan: 0x3EF2E0, green: 0x7CFF6B, amber: 0xFFB23E, dim: 0x6E8F8B, white: 0xFFFFFF };
const BOX = { closed: [0.49, 1.0, 0.42, 1], open: [1.0, 0.70, 0.24, 0.85], unchecked: [0.43, 0.56, 0.55, 0.35] };
const FIND = { guardian: 0x4FA3FF, nonhuman: 0x7CFF6B, brain: 0xB57CFF };

export function createGalaxy3D(host, overlay, hooks = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.domElement.className = "gal-gl";
  host.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.12; controls.screenSpacePanning = true;
  controls.minDistance = 2; controls.maxDistance = 60000;
  const root = new THREE.Group(); scene.add(root);
  const layer = {};                // name -> THREE.Object3D
  let data = null, on = {}, W = 1, H = 1, dirty = true, tween = null, picks = [], hover = null;
  let segEnd = [], replay = 1, running = true, mark = null;   // mark: the focus (when it is not you)      // segEnd[i]: path index where segment i ends

  function dispose(o) { o.traverse((n) => { if (n.geometry) n.geometry.dispose(); if (n.material) n.material.dispose(); }); }
  function clear() { segEnd = []; for (const o of [...root.children]) { root.remove(o); dispose(o); } for (const k in layer) delete layer[k]; }

  function lineObj(points, colour, opacity, dashed, dash) {
    const geo = new THREE.BufferGeometry().setFromPoints(points);
    const mat = dashed ? new THREE.LineDashedMaterial({ color: colour, transparent: true, opacity, dashSize: dash, gapSize: dash * 0.8 })
      : new THREE.LineBasicMaterial({ color: colour, transparent: true, opacity });
    const l = new THREE.Line(geo, mat);
    if (dashed) l.computeLineDistances();
    return l;
  }

  function build() {
    clear();
    if (!data) return;
    const extent = span();
    // galactic plane grid around the data, at y = 0
    const c = centre();
    const gs = Math.pow(10, Math.ceil(Math.log10(Math.max(100, extent * 2))));
    const grid = new THREE.GridHelper(gs, 20, 0x2a5551, 0x163330);
    grid.position.set(c.x, 0, c.z); grid.material.transparent = true; grid.material.opacity = 0.35;
    root.add(grid); layer.grid = grid;
    // path: segments with colours by age (replay draws a growing prefix)
    if (data.path.length > 1) {
      const pos = [], colr = [];
      const t0 = data.path[0].t || 0, t1 = data.path[data.path.length - 1].t || 1, sp = Math.max(1, t1 - t0);
      for (let i = 1; i < data.path.length; i++) {
        const a = data.path[i - 1], b = data.path[i];
        if (b.kind === "login" && Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) > 100) continue;
        const k = ((b.t || t0) - t0) / sp;
        const r = (181 - 119 * k) / 255, gg = (124 + 118 * k) / 255, bb = (255 - 31 * k) / 255;
        pos.push(a.x, a.y, -a.z, b.x, b.y, -b.z); colr.push(r, gg, bb, r, gg, bb); segEnd.push(i);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(colr, 3));
      const segs = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95 }));
      root.add(segs); layer.path = segs;
      applyReplay();
    }
    // systems as points
    if (data.systems.length) {
      const pos = [], colr = [];
      for (const s of data.systems) {
        pos.push(s.x, s.y, -s.z);
        const cc = new THREE.Color(s.u ? COL.violet : s.v ? COL.green : COL.dim);
        colr.push(cc.r, cc.g, cc.b);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(colr, 3));
      const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: 3, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.85 }));
      root.add(pts); layer.systems = pts;
    }
    // boxels of the active sphere: cube edges by status, closed/open filled faintly
    if (data.boxels.length && data.boxel_size) {
      const s = data.boxel_size, e = new THREE.EdgesGeometry(new THREE.BoxGeometry(s, s, s));
      const ep = e.attributes.position.array;
      const pos = [], colr = [];
      const fill = { closed: [], open: [] };
      for (const b of data.boxels) {
        const k = BOX[b.status] || BOX.unchecked;
        for (let i = 0; i < ep.length; i += 3) {
          pos.push(ep[i] + b.x, ep[i + 1] + b.y, ep[i + 2] - b.z);
          colr.push(k[0] * k[3], k[1] * k[3], k[2] * k[3]);       // dimmer = fainter on dark
        }
        if (fill[b.status]) fill[b.status].push(b);
      }
      e.dispose();
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(colr, 3));
      const grp = new THREE.Group();
      grp.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.38,
        depthWrite: false })));
      const box = new THREE.BoxGeometry(s * 0.98, s * 0.98, s * 0.98);
      for (const [st, list] of Object.entries(fill)) {
        if (!list.length) continue;
        const m = new THREE.InstancedMesh(box, new THREE.MeshBasicMaterial({ color: st === "closed" ? COL.green : COL.amber,
          transparent: true, opacity: st === "closed" ? 0.07 : 0.05, depthWrite: false }), list.length);
        const mx = new THREE.Matrix4();
        list.forEach((b, i) => { mx.makeTranslation(b.x, b.y, -b.z); m.setMatrixAt(i, mx); });
        grp.add(m);
      }
      root.add(grp); layer.boxels = grp;
    }
    // survey spheres as wire globes
    const sg = new THREE.Group();
    for (const sp of data.spheres) {
      const act = data.active && Math.abs(sp.x - data.active.x) < 0.01 && Math.abs(sp.z - data.active.z) < 0.01;
      const w = new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.SphereGeometry(sp.r, 24, 14)),
        new THREE.LineBasicMaterial({ color: act ? COL.cyan : COL.dim, transparent: true, opacity: act ? 0.22 : 0.1 }));
      w.position.copy(P(sp)); sg.add(w);
    }
    root.add(sg); layer.spheres = sg;
    // carrier path
    if (data.carrier.length > 1) {
      const l = lineObj(data.carrier.map(P), COL.amber, 0.75, true, Math.max(2, extent / 150));
      root.add(l); layer.carrier = l;
    }
    // plotted route
    if (data.navroute.length > 1) {
      const l = lineObj(data.navroute.map(P), COL.amber, 1, true, Math.max(1, extent / 300));
      root.add(l); layer.navroute = l;
    }
    // the carrier where it is now, and a jump still to come
    if (data.carrier_now) {
      const cn = data.carrier_now, grp = new THREE.Group();
      grp.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints([P(cn)]),
        new THREE.PointsMaterial({ size: 11, sizeAttenuation: false, color: COL.amber })));
      if (cn.jump && cn.jump.x !== undefined) grp.add(lineObj([P(cn), P(cn.jump)], COL.amber, 0.9, true, Math.max(1, extent / 300)));
      root.add(grp); layer.carriernow = grp;
    }
    // finds as small diamonds (points)
    if (data.finds.length) {
      const g = new THREE.Group();
      for (const f of data.finds) {
        const geo = new THREE.BufferGeometry().setFromPoints([P(f)]);
        g.add(new THREE.Points(geo, new THREE.PointsMaterial({ size: 7, sizeAttenuation: false, color: FIND[f.kinds[0]] || COL.white })));
      }
      root.add(g); layer.finds = g;
    }
    // you + direction to the core
    if (data.you) {
      const you = P(data.you);
      const m = new THREE.Points(new THREE.BufferGeometry().setFromPoints([you]),
        new THREE.PointsMaterial({ size: 9, sizeAttenuation: false, color: COL.white }));
      root.add(m);
      const dir = new THREE.Vector3(CORE[0], CORE[1], -CORE[2]).sub(you).normalize();
      root.add(new THREE.ArrowHelper(dir, you, Math.max(20, extent * 0.25), COL.dim, extent * 0.03, extent * 0.015));
    }
    applyLayers();
    dirty = true;
  }

  function applyLayers() {
    if (layer.carriernow) layer.carriernow.visible = on.carrier !== false;
    for (const k of ["path", "carrier", "systems", "boxels", "spheres", "finds", "navroute"]) {
      if (layer[k]) layer[k].visible = on[k] !== false;
    }
    dirty = true;
  }

  function applyReplay() {
    if (!layer.path) return;
    const last = Math.round((data.path.length - 1) * replay);
    let n = 0; while (n < segEnd.length && segEnd[n] <= last) n++;
    layer.path.geometry.setDrawRange(0, n * 2);
    dirty = true;
  }

  function centre() {
    if (data && data.active) return { x: data.active.x, y: data.active.y, z: -data.active.z };
    if (data && data.you) return { x: data.you.x, y: data.you.y, z: -data.you.z };
    return { x: 0, y: 0, z: 0 };
  }
  function span() {
    if (!data) return 100;
    const pts = data.path.length ? data.path : data.systems;
    if (!pts.length) return 100;
    const xs = pts.map(p => p.x), zs = pts.map(p => p.z), ys = pts.map(p => p.y);
    return Math.max(50, Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs), Math.max(...ys) - Math.min(...ys));
  }
  function bounds() {
    const pts = (data.path.length ? data.path : data.systems).map(P);
    if (data.you) pts.push(P(data.you));
    const b = new THREE.Box3().setFromPoints(pts.length ? pts : [new THREE.Vector3()]);
    return b;
  }

  // ------------------------------------------------------------ camera
  function goTo(target, pos) { tween = { t0: performance.now(), ta: controls.target.clone(), tb: target, pa: camera.position.clone(), pb: pos }; }
  function look(target, dist, dirv) { goTo(target, target.clone().addScaledVector(dirv.normalize(), dist)); }
  const api = {
    setData(d, layers) { const first = !data; data = d; on = layers || on; build(); if (first) api.view("all", true); },
    setLayers(layers) { on = layers; applyLayers(); },
    setReplay(k) { replay = Math.max(0, Math.min(1, k)); applyReplay(); },
    replayHead() {
      if (!data || !data.path.length) return null;
      const i = Math.max(0, Math.min(data.path.length - 1, Math.round((data.path.length - 1) * replay)));
      return data.path[i];
    },
    // turn around another point: keep the camera's offset unless a distance is given
    focusOn(f, opts = {}) {
      if (!f) return;
      mark = opts.me ? null : f;
      const target = P(f);
      let off = camera.position.clone().sub(controls.target);
      if (opts.dist) off = off.lengthSq() > 0 ? off.normalize().multiplyScalar(opts.dist) : new THREE.Vector3(0, 0.7, 0.7).multiplyScalar(opts.dist);
      const pos = target.clone().add(off);
      if (opts.instant) { controls.target.copy(target); camera.position.copy(pos); controls.update(); tween = null; }
      else goTo(target, pos);
      dirty = true;
    },
    meDistance() { return Math.max(150, (data && data.boxel_size || 20) * 8); },
    view(what, instant) {
      if (!data) return;
      let target, dist, dirv = new THREE.Vector3(0, 0.7, 0.7);
      if (what === "sphere" && data.active) { target = P(data.active); dist = data.active.r * 3.2; }
      else if (what === "me" && data.you) { target = P(data.you); dist = api.meDistance(); }
      else {
        const b = bounds(); target = b.getCenter(new THREE.Vector3());
        dist = Math.max(80, b.getSize(new THREE.Vector3()).length() * 0.9);
      }
      if (what === "top") dirv = new THREE.Vector3(0, 1, 0.001);
      if (what === "side") dirv = new THREE.Vector3(0, 0.02, 1);
      if (instant) { controls.target.copy(target); camera.position.copy(target.clone().addScaledVector(dirv.normalize(), dist)); controls.update(); dirty = true; tween = null; }
      else look(target, dist, dirv);
    },
    canvas: renderer.domElement,
    destroy() { running = false; clear(); renderer.dispose(); renderer.domElement.remove(); },
    redraw() { dirty = true; },
  };

  // ------------------------------------------------------------ labels, picking
  const v = new THREE.Vector3();
  function project(x, y, z) { v.set(x, y, z).project(camera); return [(v.x + 1) / 2 * W, (1 - v.y) / 2 * H, v.z > -1 && v.z < 1]; }
  function drawOverlay() {
    const dpr = window.devicePixelRatio || 1;
    overlay.width = Math.max(1, W * dpr); overlay.height = Math.max(1, H * dpr);
    const g = overlay.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    picks = [];
    if (!data) return;
    g.font = "11px monospace";
    const label = (o, txt, colr) => { const [x, y, ok] = project(o.x, o.y, -o.z); if (!ok) return; g.fillStyle = colr; g.fillText(txt, x + 7, y - 6); };
    if (on.spheres !== false) for (const sp of data.spheres) label({ x: sp.x, y: sp.y + sp.r, z: sp.z }, sp.label, "#3EF2E0");
    if (data.you) label(data.you, hooks.t ? hooks.t("you") : "you", "#FFFFFF");
    if (mark) {                                   // the focus: amber ring and name
      const [x, y, ok] = project(mark.x, mark.y, -mark.z);
      if (ok) { g.strokeStyle = "#FFB23E"; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, 9, 0, Math.PI * 2); g.stroke();
        if (mark.kind !== "carrier") { g.fillStyle = "#FFB23E"; g.fillText(mark.name || "", x + 12, y + 4); } }
    }
    label({ x: 0, y: 0, z: 0 }, "Sol", "#FFF4E8");
    { const [x, y, ok] = project(0, 0, 0); if (ok) { g.fillStyle = "#FFF4E8"; g.beginPath(); g.arc(x, y, 3, 0, Math.PI * 2); g.fill(); } }
    if (on.navroute !== false) data.navroute.forEach((h, i) => { if (i) label(h, String(i), "#FFB23E"); });
    if (on.carrier !== false && data.carrier_now && hooks.carrierTexts) {
      const cn = data.carrier_now, [main, jump] = hooks.carrierTexts(cn);
      label(cn, main, "#FFB23E");
      if (jump && cn.jump.x !== undefined) label(cn.jump, jump, "#FFB23E");
    }
    // replay head
    if (replay < 1) {
      const h = api.replayHead();
      if (h) {
        const [x, y, ok] = project(h.x, h.y, -h.z);
        if (ok) { g.strokeStyle = "#FFFFFF"; g.beginPath(); g.arc(x, y, 6, 0, Math.PI * 2); g.stroke();
          g.fillStyle = "#FFFFFF"; g.fillText(h.name + (h.t ? " · " + new Date(h.t * 1000).toLocaleDateString() : ""), x + 9, y + 14); }
      }
    }
    // pick candidates (screen space, like the 2D map)
    // same shape as the 2D picks, so the view's label() works for both
    const add = (o, p) => { const [x, y, ok] = project(o.x, o.y, -o.z); if (ok && x > 0 && y > 0 && x < W && y < H) picks.push(Object.assign({ sx: x, sy: y }, p)); };
    if (on.systems !== false) for (const s of data.systems) add(s, { kind: "system", s, id: s.id });
    if (on.path !== false) {
      const last = Math.round((data.path.length - 1) * replay);
      data.path.forEach((p, i) => { if (i <= last) add(p, { kind: "jump", p, id: p.id64 }); });
    }
    if (on.carrier !== false) for (const c of data.carrier) add(c, { kind: "carrier", c, id: c.id });
    if (on.carrier !== false && data.carrier_now) add(data.carrier_now, { kind: "carriernow", c: data.carrier_now, id: data.carrier_now.id });
    if (on.finds !== false) for (const f of data.finds) add(f, { kind: "find", f, id: f.id });
    if (hover) {
      const txt = hooks.label ? hooks.label(hover) : "";
      if (txt) {
        g.font = "12px monospace"; const w = g.measureText(txt).width + 10;
        const x = Math.min(W - w - 4, hover.sx + 10), y = Math.max(16, hover.sy - 12);
        g.fillStyle = "rgba(5,12,13,.88)"; g.fillRect(x, y - 13, w, 18);
        g.strokeStyle = "rgba(62,242,224,.4)"; g.strokeRect(x, y - 13, w, 18);
        g.fillStyle = "#CFEDEA"; g.fillText(txt, x + 5, y);
      }
    }
  }
  let downAt = null;
  function nearest(e, rad) {
    const r = renderer.domElement.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    let best = null, bd = rad * rad;
    // later = drawn on top: wins a tie
    for (const p of picks) { const d = (p.sx - x) ** 2 + (p.sy - y) ** 2; if (d <= bd) { bd = d; best = p; } }
    return best;
  }
  function setHover(p) { if (p !== hover) { hover = p; renderer.domElement.style.cursor = p && p.id ? "pointer" : ""; dirty = true; } }
  renderer.domElement.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointermove", (e) => { if (e.buttons === 0) setHover(nearest(e, 10)); });
  renderer.domElement.addEventListener("pointerup", (e) => {
    const moved = !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4;
    downAt = null;
    if (moved) return;
    // a click or tap puts the focus there (touch: also shows the label)
    const p = nearest(e, e.pointerType === "touch" ? 22 : 10);
    if (e.pointerType === "touch") setHover(p);
    if (p && hooks.pick) hooks.pick(p);
  });
  renderer.domElement.addEventListener("dblclick", (e) => {
    const p = nearest(e, 14);
    if (p && p.id && hooks.open) hooks.open(p);
  });

  function resize() {
    W = Math.max(1, host.clientWidth); H = Math.max(1, host.clientHeight);
    renderer.setSize(W, H, false);
    renderer.domElement.style.width = W + "px"; renderer.domElement.style.height = H + "px";
    camera.aspect = W / H; camera.updateProjectionMatrix(); dirty = true;
  }
  controls.addEventListener("change", () => { dirty = true; });
  function loop(t) {
    if (!running) return;
    if (tween) {
      const k = Math.min(1, (t - tween.t0) / 700), e = 1 - Math.pow(1 - k, 3);
      controls.target.lerpVectors(tween.ta, tween.tb, e);
      camera.position.lerpVectors(tween.pa, tween.pb, e);
      dirty = true; if (k >= 1) tween = null;
    }
    controls.update();
    if (dirty && !document.hidden && host.clientWidth > 0 && renderer.domElement.style.display !== "none") { renderer.render(scene, camera); drawOverlay(); dirty = false; }
    requestAnimationFrame(loop);
  }
  new ResizeObserver(resize).observe(host);
  resize();
  requestAnimationFrame(loop);
  return api;
}
