// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// Out in the Rhino (MINING and PLANET): the rig being collected, the
// Rhino's hold, and the ship's - its hold takes the Rhino's load when it
// docks (4.12, the plugin's groundmine: the same numbers as the overlay).

import { el } from "../ui.js";
import { t } from "../i18n.js";

export function rhinoHold(h) {
  const box = el("div", { class: "rhino-hold small" });
  const g = h.rig;
  if (g && g.n) {
    box.append(el("div", { class: "c-amber", text: g.collecting
      ? t("Rig {n}: {got}/{r} t · {trip} t this trip", { n: g.n, got: g.t, r: h.rig_t, trip: g.trip_t })
      : t("{n} rig(s) · {trip} t this trip", { n: g.n, trip: g.trip_t }) }));
  }
  const rhinoTight = h.limit === "rhino" && h.short;
  box.append(el("div", { class: rhinoTight ? "c-amber" : "c-dim",
    text: t("Rhino {u}/{c} t · {f} t free · full rigs: {n}", { u: h.used, c: h.capacity, f: h.free, n: h.rigs_fit }) }));
  if (h.ship_free_after !== undefined && h.ship_free_after !== null) {
    box.append(el("div", { class: h.limit === "ship" ? "c-amber" : "c-dim",
      text: t("Ship: {f} t free with the Rhino's {u} t aboard", { f: h.ship_free_after, u: h.used }) }));
  }
  if (h.short) {
    box.append(el("div", { class: "c-red", text: h.limit === "ship"
      ? t("Ship full - make room before the next rig ({r} t)", { r: h.rig_t })
      : t("Rhino full - a full rig ({r} t) no longer fits, make room before collecting", { r: h.rig_t }) }));
  } else if (h.limit === "ship") {
    box.append(el("div", { class: "c-amber",
      text: t("The ship is the limit: {m} t more ({n} full rigs)", { m: h.room, n: h.room_rigs }) }));
  }
  return box;
}
