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
  const es = new EventSource(url);
  es.onopen = () => handlers.open && handlers.open();
  es.onerror = () => handlers.error && handlers.error(es.readyState);
  for (const ev of ["snapshot", "jump", "target", "scan", "status"]) {
    es.addEventListener(ev, (m) => {
      let data = null;
      try { data = JSON.parse(m.data); } catch { /* ignore broken frame */ }
      handlers[ev] && handlers[ev](data);
    });
  }
  return es;
}
