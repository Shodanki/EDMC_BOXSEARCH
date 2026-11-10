// JSON API and Server-Sent Events. The LAN token (if any) travels as a
// cookie set when the page was opened with ?token=..., so nothing here
// needs to know it; it is still forwarded as a header when present in the URL.

const token = new URLSearchParams(location.search).get("token");

export async function getJSON(path) {
  const headers = token ? { "X-FIS-Token": token } : {};
  const r = await fetch(path, { headers, cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(path + " → HTTP " + r.status);
  return r.json();
}

/** A same-site URL for <img> and links, with the LAN token when the page has one. */
export function withToken(path) {
  return token ? path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token) : path;
}

/** POST to the settings endpoint: the custom header keeps other sites out. */
export async function postJSON(path, body) {
  const headers = { "Content-Type": "application/json", "X-FIS-Settings": "1" };
  if (token) headers["X-FIS-Token"] = token;
  const r = await fetch(path, { method: "POST", headers, body: JSON.stringify(body), cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

/**
 * Subscribe to /api/events. handlers: { snapshot, jump, target, scan, status,
 * open, error }. EventSource reconnects on its own; we only report the state.
 */
export function subscribe(handlers) {
  const url = "/api/events" + (token ? "?token=" + encodeURIComponent(token) : "");
  let es = null, last = Date.now();
  const connect = () => {
    es = new EventSource(url);
    es.onopen = () => { last = Date.now(); handlers.open && handlers.open(); };
    es.onerror = () => handlers.error && handlers.error(es.readyState);
    for (const ev of ["snapshot", "jump", "target", "scan", "status", "ping"]) {
      es.addEventListener(ev, (m) => {
        last = Date.now();
        let data = null;
        try { data = JSON.parse(m.data); } catch { /* ignore broken frame */ }
        handlers[ev] && handlers[ev](data);
      });
    }
  };
  connect();
  // watchdog: the server sends something at least every 15 s (a ping when
  // the game is quiet). A link that went silent - tablet asleep, Wi-Fi, a
  // half-open connection - is dropped and opened again; the new snapshot
  // brings every view up to date.
  setInterval(() => {
    if (Date.now() - last < STALE_MS) return;
    last = Date.now();
    try { es.close(); } catch { /* already gone */ }
    handlers.stale && handlers.stale();
    connect();
  }, 5000);
  return { close: () => es.close() };
}

const STALE_MS = 40000;
