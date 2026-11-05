// 3D renderer for TAKTIK (Three.js, loaded by the browser from the CDN).
// Expanse-like: thin orbit lines, faint range rings, lines instead of
// surfaces; labels live on the shared 2D overlay (scene.js).

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { UI } from "./scene.js";

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.25, "rgba(255,255,255,.35)");
  grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

export function create3D(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.domElement.className = "tac-gl";
  container.prepend(renderer.domElement);
  const scene3 = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 50000);
  camera.position.set(0, 60, 80);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.screenSpacePanning = true;
  controls.minDistance = 0.3;
  controls.maxDistance = 20000;
  const root = new THREE.Group();
  scene3.add(root);
  const glow = glowTexture();
  const sphere = new THREE.SphereGeometry(1, 28, 18);
  const api = { kind: "3d", onFrame: null };
  let W = 1, H = 1, scene = null, tween = null, dirty = true;

  function clear() {
    for (const o of [...root.children]) {
      root.remove(o);
      o.traverse((n) => {
        if (n.geometry && n.geometry !== sphere) n.geometry.dispose();
        if (n.material) n.material.dispose();
      });
    }
  }

  function line(points, colour, opacity, dashed = false, width = 1) {
    const geo = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(p[0], p[1], p[2])));
    const mat = dashed
      ? new THREE.LineDashedMaterial({ color: colour, transparent: true, opacity, dashSize: 0.6, gapSize: 0.5 })
      : new THREE.LineBasicMaterial({ color: colour, transparent: true, opacity, linewidth: width });
    const l = new THREE.Line(geo, mat);
    if (dashed) l.computeLineDistances();
    return l;
  }

  function build() {
    clear();
    if (!scene) return;
    // range rings + spokes in the reference plane
    for (const r of scene.rings) {
      const pts = [];
      for (let i = 0; i <= 128; i++) { const a = i / 128 * Math.PI * 2; pts.push([Math.cos(a) * r.radius, 0, Math.sin(a) * r.radius]); }
      root.add(line(pts, 0x3EF2E0, 0.09));
    }
    const R = scene.rings.length ? scene.rings[scene.rings.length - 1].radius : 50;
    for (let a = 0; a < 12; a++) {
      const t = a * Math.PI / 6;
      root.add(line([[0, 0, 0], [Math.cos(t) * R, 0, Math.sin(t) * R]], 0x3EF2E0, 0.04));
    }
    // orbits
    for (const b of scene.bodies) {
      if (b.orbit) root.add(line(b.orbit, 0x3EF2E0, b.moon ? 0.13 : 0.24));
    }
    // route
    for (const l of scene.route) {
      const col = l.isNext ? 0xFFB23E : (l.done ? 0x6E8F8B : 0x3EF2E0);
      root.add(line([l.a, l.b], col, l.isNext ? 1 : (l.done ? 0.5 : 0.75), l.done));
    }
    // bodies
    for (const b of scene.bodies) {
      const colour = new THREE.Color(b.colour);
      const mat = b.kind === "Star"
        ? new THREE.MeshBasicMaterial({ color: colour })
        : new THREE.MeshBasicMaterial({ color: colour.clone().multiplyScalar(0.8) });
      const m = new THREE.Mesh(sphere, mat);
      m.position.set(b.p[0], b.p[1], b.p[2]);
      m.scale.setScalar(b.size);
      m.userData.id = b.id;
      root.add(m);
      // dark terminator rim: a thin outline reads better than shading here
      if (b.kind !== "Star") {
        const rim = new THREE.Mesh(sphere, new THREE.MeshBasicMaterial({ color: 0x05080A, side: THREE.BackSide, transparent: true, opacity: 0.9 }));
        rim.position.copy(m.position); rim.scale.setScalar(b.size * 1.08);
        root.add(rim);
      } else {
        const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: colour, transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
        s.position.copy(m.position); s.scale.setScalar(b.size * 7);
        root.add(s);
      }
      for (const ring of b.rings) {
        const rg = new THREE.RingGeometry(ring.inner, ring.outer, 64);
        const rm = new THREE.Mesh(rg, new THREE.MeshBasicMaterial({ color: 0xDCC8AA, side: THREE.DoubleSide, transparent: true, opacity: 0.14, depthWrite: false }));
        rm.position.copy(m.position);
        rm.rotation.x = -Math.PI / 2 + 0.35;
        root.add(rm);
        // crisp edges: lines first, faint surface second
        for (const rad of [ring.inner, ring.outer]) {
          const pts = [];
          for (let i = 0; i <= 96; i++) { const a = i / 96 * Math.PI * 2; pts.push([Math.cos(a) * rad, Math.sin(a) * rad, 0]); }
          const edge = line(pts, 0xDCC8AA, 0.55);
          edge.position.copy(m.position);
          edge.rotation.x = -Math.PI / 2 + 0.35;
          root.add(edge);
        }
      }
    }
    dirty = true;
  }

  function resize() {
    W = Math.max(1, container.clientWidth); H = Math.max(1, container.clientHeight);
    renderer.setSize(W, H, false);
    renderer.domElement.style.width = W + "px"; renderer.domElement.style.height = H + "px";
    camera.aspect = W / H; camera.updateProjectionMatrix();
    dirty = true;
  }

  const v = new THREE.Vector3();
  api.project = (p) => {
    v.set(p[0], p[1], p[2]).project(camera);
    return { x: (v.x + 1) / 2 * W, y: (1 - v.y) / 2 * H, ok: v.z > -1 && v.z < 1, depth: v.z };
  };
  api.radiusPx = (size, p) => {
    const d = camera.position.distanceTo(new THREE.Vector3(p[0], p[1], p[2]));
    return Math.max(1.5, size / (d * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) * H / 2);
  };

  function goTo(target, dist) {
    const dir = camera.position.clone().sub(controls.target).normalize();
    if (dir.lengthSq() < 1e-6) dir.set(0, 0.6, 0.8);
    tween = { t0: performance.now(), ta: controls.target.clone(), tb: new THREE.Vector3(...target),
              da: camera.position.distanceTo(controls.target), db: dist, dir };
  }
  api.focus = (c, r) => goTo(c, Math.max(1.2, r * 3.2));
  api.overview = (instant) => {
    if (!scene) return;
    const d = scene.extent * 2.2;
    if (instant) {
      tween = null;
      controls.target.set(0, 0, 0);
      camera.position.set(0, d * 0.55, d * 0.85);
      controls.update(); dirty = true;
    } else goTo([0, 0, 0], d);
  };
  api.setScene = (s, keepView) => {
    const first = !scene;
    scene = s;
    build();
    if (first || !keepView) api.overview(true);
  };
  api.redraw = () => { dirty = true; };
  api.resize = resize;

  controls.addEventListener("change", () => { dirty = true; });
  let downAt = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    api.dragged = downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4;
  });

  let running = true;
  function loop(t) {
    if (!running) return;
    if (tween) {
      const k = Math.min(1, (t - tween.t0) / 650), e = 1 - Math.pow(1 - k, 3);
      controls.target.lerpVectors(tween.ta, tween.tb, e);
      const d = tween.da * Math.pow(tween.db / tween.da, e);
      camera.position.copy(controls.target).addScaledVector(tween.dir, d);
      dirty = true;
      if (k >= 1) tween = null;
    }
    controls.update();
    if (dirty && !document.hidden) {
      renderer.render(scene3, camera);
      api.onFrame && api.onFrame();
      dirty = false;
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  api.camera = camera; api.controls = controls;
  api.element = renderer.domElement;
  api.destroy = () => { running = false; clear(); renderer.dispose(); renderer.domElement.remove(); };
  new ResizeObserver(resize).observe(container);
  resize();
  return api;
}

export const COLOURS_UI = UI;
