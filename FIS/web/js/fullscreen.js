// Full screen from inside the page (Fullscreen API). Browsers allow it only
// as the answer to a click or key press - never on their own at page load.
// Desktop Chrome/Edge/Firefox and Android Chrome: the whole page. iPad Safari:
// prefixed API; iPhone Safari has none - there "Add to Home Screen" opens the
// FIS without browser bars (see the apple-mobile-web-app meta tags).

import { t } from "./i18n.js";

const doc = document;
const el = doc.documentElement;

export function supported() {
  return !!(doc.fullscreenEnabled || doc.webkitFullscreenEnabled);
}

export function active() {
  return !!(doc.fullscreenElement || doc.webkitFullscreenElement);
}

export async function toggle() {
  try {
    if (active()) {
      await (doc.exitFullscreen ? doc.exitFullscreen() : doc.webkitExitFullscreen());
    } else {
      await (el.requestFullscreen ? el.requestFullscreen({ navigationUI: "hide" }) : el.webkitRequestFullscreen());
    }
  } catch (e) {
    /* refused (no user gesture, or blocked by the browser) – nothing to do */
  }
}

/** A ⛶ button that toggles full screen; hidden where the browser cannot. */
export function button(cls) {
  const b = doc.createElement("button");
  b.className = "fs-btn " + (cls || "");
  const sync = () => {
    const on = active();
    b.textContent = on ? "⤡" : "⛶";
    b.title = (on ? t("leave full screen") : t("full screen")) + " (F)";
    b.setAttribute("aria-pressed", on ? "true" : "false");
  };
  b.addEventListener("click", toggle);
  doc.addEventListener("fullscreenchange", sync);
  doc.addEventListener("webkitfullscreenchange", sync);
  sync();
  if (!supported()) b.hidden = true;
  return b;
}
