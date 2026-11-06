// SETTINGS – what fis_settings.bat asks, in the browser. Only on the game PC
// (the server answers nobody else): default language, open the browser at
// start, home network for a tablet - with the address to type there.

import { getJSON, postJSON } from "../api.js";
import { el, frame } from "../ui.js";
import { t } from "../i18n.js";

let root = null, data = null, msg = "";

export function mount(r) { root = r; root.classList.add("settings-view"); }

export async function update(ctx, reason) {
  if (!root || (reason !== "show" && data)) return;
  try { data = await getJSON("/api/settings"); } catch (e) { data = { error: true }; }
  render();
}

function render() {
  root.replaceChildren();
  if (!data || data.error) {
    root.append(frame(t("SETTINGS"), "", el("div", { class: "empty" }, t("Settings only on the game PC."), el("br"),
      el("span", { class: "c-dim", text: t("Open the FIS there (http://127.0.0.1:{p}/) or use fis_settings.bat.", { p: location.port || "8765" }) }))));
    return;
  }
  const lang = el("select", { class: "lay-pick" }, el("option", { value: "en", text: "English" }), el("option", { value: "de", text: "Deutsch" }));
  lang.value = data.language;
  const browser = el("input", { type: "checkbox", checked: data.open_browser ? true : null });
  const lan = el("input", { type: "checkbox", checked: data.lan ? true : null });
  const save = async () => {
    try {
      data = await postJSON("/api/settings", { language: lang.value, open_browser: browser.checked, lan: lan.checked });
      msg = data.restart ? t("Saved. Restart the FIS (or EDMC with autostart) for the home network change.") : t("Saved.");
    } catch (e) { msg = t("Could not save: {e}", { e: e.message }); }
    render();
  };
  const rows = [
    el("label", { class: "st-set" }, el("span", { text: t("Default language") }), lang),
    el("div", { class: "c-dim small", text: t("Each browser can still switch with EN / DE at the bottom.") }),
    el("label", { class: "st-set" }, el("span", { text: t("Open the browser when the FIS starts") }), browser),
    el("label", { class: "st-set" }, el("span", { text: t("Home network (tablet, second PC)") }), lan),
    el("div", { class: "c-dim small", text: t("Other devices need the address below with its token; the FIS then answers the home network too.") }),
    el("button", { onclick: save, text: t("Save") }),
    msg ? el("div", { class: "c-green small", text: msg }) : null,
  ];
  const lanRows = [];
  if (data.lan && data.lan_urls && data.lan_urls.length) {
    lanRows.push(el("div", { class: "c-dim small", text: t("Type this on the tablet (same home network):") }));
    for (const u of data.lan_urls) lanRows.push(el("div", { class: "st-url" }, el("code", { text: u }),
      el("button", { text: t("copy"), onclick: () => navigator.clipboard && navigator.clipboard.writeText(u) })));
    if (data.running_lan === false) lanRows.push(el("div", { class: "c-amber small", text: t("Not active yet - restart the FIS.") }));
    if (data.firewall === "") lanRows.push(el("div", { class: "c-amber small", text: t("No firewall rule lets other devices in - fis_settings.bat can add one (Windows asks for permission).") }));
    else if (data.firewall) lanRows.push(el("div", { class: "c-green small", text: t("Firewall rule: {r}", { r: data.firewall }) }));
  }
  root.append(el("div", { class: "st-grid" },
    frame(t("SETTINGS"), t("only on this PC"), rows, { appear: false }),
    data.lan ? frame(t("HOME NETWORK"), "", lanRows.length ? lanRows : el("div", { class: "c-dim", text: t("Save to create the address.") }), { appear: false }) : null,
    el("div", { class: "c-dim small", text: t("Stored in {f}.", { f: data.ini }) })));
}
