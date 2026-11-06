// 2D fallback for SYSTEM (no internet → no Three.js): top-down canvas with
// the same scene model, labels and controls (wheel zoom, drag pan).

import { UI } from "./scene.js";

export function create2D(container) {
  const cv = document.createElement("canvas");
  cv.className = "tac-gl";
  container.prepend(cv);
  const g = cv.getContext("2d");
  let scene = null;
  let view = { x: 0, z: 0, zoom: 4 };
  let tween = null;
  let W = 0, H = 0, dpr = 1;
  const api = { kind: "2d", onFrame: null };

  function resize() {
    dpr = window.devicePixelRatio || 1;
    W = container.clientWidth; H = container.clientHeight;
    cv.width = Math.max(1, W * dpr); cv.height = Math.max(1, H * dpr);
    cv.style.width = W + "px"; cv.style.height = H + "px";
    draw();
  }
  const P = (p) => ({ x: W / 2 + (p[0] - view.x) * view.zoom, y: H / 2 + (p[2] - view.z) * view.zoom });

  api.project = (p) => { const s = P(p); s.ok = true; return s; };
  api.radiusPx = (size) => Math.max(2, size * view.zoom);

  function draw() {
    if (!scene) { g.clearRect(0, 0, cv.width, cv.height); api.onFrame && api.onFrame(); return; }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const o = P([0, 0, 0]);
    // distance rings + spokes
    g.lineWidth = 1;
    for (const r of scene.rings) {
      g.strokeStyle = "rgba(62,242,224,.10)";
      g.beginPath(); g.arc(o.x, o.y, r.radius * view.zoom, 0, Math.PI * 2); g.stroke();
    }
    g.strokeStyle = "rgba(62,242,224,.05)";
    const R = (scene.rings.length ? scene.rings[scene.rings.length - 1].radius : 50) * view.zoom;
    for (let a = 0; a < 12; a++) {
      g.beginPath(); g.moveTo(o.x, o.y);
      g.lineTo(o.x + Math.cos(a * Math.PI / 6) * R, o.y + Math.sin(a * Math.PI / 6) * R); g.stroke();
    }
    // orbits
    for (const b of scene.bodies) {
      if (!b.orbit) continue;
      g.strokeStyle = b.moon ? "rgba(62,242,224,.14)" : "rgba(62,242,224,.24)";
      g.beginPath();
      b.orbit.forEach((q, i) => { const s = P(q); i ? g.lineTo(s.x, s.y) : g.moveTo(s.x, s.y); });
      g.stroke();
    }
    // route
    for (const l of scene.route) {
      const a = P(l.a), c = P(l.b);
      g.strokeStyle = l.isNext ? UI.amber : (l.done ? "rgba(110,143,139,.55)" : "rgba(62,242,224,.75)");
      g.lineWidth = l.isNext ? 2 : 1.2;
      g.setLineDash(l.done ? [4, 4] : []);
      g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(c.x, c.y); g.stroke();
    }
    g.setLineDash([]);
    // bodies
    for (const b of scene.bodies) {
      const s = P(b.p), r = api.radiusPx(b.size);
      for (const ring of b.rings) {
        g.strokeStyle = "rgba(220,200,170,.45)";
        g.lineWidth = Math.max(1, (ring.outer - ring.inner) * view.zoom);
        g.beginPath(); g.arc(s.x, s.y, (ring.inner + ring.outer) / 2 * view.zoom, 0, Math.PI * 2); g.stroke();
      }
      g.lineWidth = 1;
      g.fillStyle = b.colour;
      if (b.kind === "Star") { g.shadowColor = b.colour; g.shadowBlur = 12; }
      g.beginPath(); g.arc(s.x, s.y, r, 0, Math.PI * 2); g.fill();
      g.shadowBlur = 0;
    }
    api.onFrame && api.onFrame();
  }

  function animate(t) {
    if (!tween) return;
    const k = Math.min(1, (t - tween.t0) / 500), e = 1 - Math.pow(1 - k, 3);
    view = { x: tween.a.x + (tween.b.x - tween.a.x) * e, z: tween.a.z + (tween.b.z - tween.a.z) * e,
             zoom: tween.a.zoom * Math.pow(tween.b.zoom / tween.a.zoom, e) };
    draw();
    if (k < 1) requestAnimationFrame(animate); else tween = null;
  }
  function goTo(b) {
    tween = { t0: performance.now(), a: { ...view }, b };
    requestAnimationFrame(animate);
  }

  api.setScene = (s, keepView) => {
    const first = !scene;
    scene = s;
    if (first || !keepView) api.overview(true);
    else draw();
  };
  api.overview = (instant) => {
    if (!scene) return;
    const z = Math.min(W, H) / 2 / (scene.extent * 1.1 || 1);
    if (instant) { tween = null; view = { x: 0, z: 0, zoom: z }; draw(); } else goTo({ x: 0, z: 0, zoom: z });
  };
  api.focus = (c, r) => goTo({ x: c[0], z: c[2], zoom: Math.min(W, H) / 2 / (r * 2.2) });
  api.redraw = draw;
  api.resize = resize;

  // interaction
  let drag = null;
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, v: { ...view }, moved: false }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    view = { ...drag.v, x: drag.v.x - dx / view.zoom, z: drag.v.z - dy / view.zoom };
    draw();
  });
  cv.addEventListener("pointerup", () => { api.dragged = drag && drag.moved; drag = null; });
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const k = Math.exp(-e.deltaY * 0.0015);
    const rect = cv.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const wx = view.x + (mx - W / 2) / view.zoom, wz = view.z + (my - H / 2) / view.zoom;
    const zoom = Math.max(0.05, Math.min(800, view.zoom * k));
    view = { zoom, x: wx - (mx - W / 2) / zoom, z: wz - (my - H / 2) / zoom };
    draw();
  }, { passive: false });
  api.element = cv;
  api.destroy = () => cv.remove();
  new ResizeObserver(resize).observe(container);
  resize();
  return api;
}
