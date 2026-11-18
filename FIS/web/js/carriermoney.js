// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
// 5.0 CT2: the own carrier's money as rows - shared by STATISTICS and
// GAIN / LOSS (fis/carriermoney.py). Frontier's figures are exact, the
// journal's upkeep is an estimate and carries "~".

import { el, fmt } from "./ui.js";
import { t, N_ } from "./i18n.js";

export const CREW_ROLE = { shipyard: N_("Shipyard"), outfitting: N_("Outfitting"), refuel: N_("Refuel"), repair: N_("Repair"),
  rearm: N_("Rearm"), voucherredemption: N_("Redemption office"), exploration: N_("Universal Cartographics"),
  bartender: N_("Bar"), vistagenomics: N_("Vista Genomics"), blackmarket: N_("Secure warehouse"),
  pioneersupplies: N_("Pioneer Supplies"), commodities: N_("Commodities") };

const CREW_OP = { Activate: N_("switched on"), Deactivate: N_("switched off"), Pause: N_("paused"), Resume: N_("resumed"),
  Replace: N_("crew replaced") };

export function crText(v, sign) {
  if (v === null || v === undefined) return "–";
  const s = sign && v > 0 ? "+ " : v < 0 ? "− " : "";
  const a = Math.abs(v);
  return s + (a >= 1e9 ? fmt(a / 1e9, 2) + " " + t("bn Cr") : a >= 1e6 ? fmt(a / 1e6, 1) + " M Cr" : fmt(a, 0) + " Cr");
}

function row(label, value, cls) {
  return el("div", { class: "st-row" }, el("span", { class: "c-dim", text: label }), el("span", { class: "num " + (cls || ""), text: value }));
}
const head = (s) => el("div", { class: "c-cyan small st-learn-h", text: s });

/** Rows for one frame: income, costs, the journal's part, the crew. */
export function carrierMoneyRows(M, opts = {}) {
  const rows = [];
  const F = M.frontier, J = M.journal;
  if (F) {
    rows.push(head(t("INCOME (FRONTIER, ALL TIME)")));
    rows.push(row(t("Market profit"), crText(F.market_profit), F.market_profit ? "c-green" : "c-dim"));
    if (F.black_profit) rows.push(row(t("Secure warehouse profit"), crText(F.black_profit), "c-green"));
    rows.push(row(t("Bar profit"), crText(F.bar_profit), F.bar_profit ? "c-green" : "c-dim"));
    rows.push(head(t("COSTS (FRONTIER, PER WEEK)")));
    rows.push(row(t("Upkeep per week"), crText(-F.per_week), "c-amber"));
    rows.push(row("  " + t("core"), crText(-F.core), "c-dim"));
    rows.push(row("  " + t("services and crew"), crText(-F.services), "c-dim"));
    rows.push(row(t("This week so far"), crText(-F.week_to_date), "c-amber"));
    if (F.jumps || F.jumps_cost) rows.push(row(t("Jumps this week"), F.jumps + " · " + crText(-F.jumps_cost), "c-dim"));
    if (F.taxation) rows.push(row(t("Taxes"), crText(-F.taxation), "c-dim"));
    if (opts.crew !== false && F.crew.length) {
      rows.push(head(t("CREW PER SERVICE (SALARY PER WEEK)")));
      for (const c of F.crew) rows.push(row((CREW_ROLE[c.role] ? t(CREW_ROLE[c.role]) : c.role) + (c.enabled ? "" : " · " + t("off")),
        crText(-c.salary), c.enabled ? "" : "c-dim"));
    }
  }
  if (J) {
    rows.push(head(t("JOURNAL (THIS PERIOD)")));
    rows.push(row(t("Paid in"), crText(J.deposit)), row(t("Taken out"), crText(J.withdraw)));
    const U = J.upkeep;
    rows.push(row(t("Upkeep (estimate)") + (U ? " · " + t("{d} days", { d: fmt(U.days, 0) }) : ""),
      U && U.cost ? "~ " + crText(-U.cost) : t("not measurable"), U && U.cost ? "c-amber" : "c-dim"));
    if (J.jumps) rows.push(row(t("Jumps ordered"), fmt(J.jumps, 0), ""));
    for (const s of J.services) rows.push(row(new Date(s.ts * 1000).toLocaleDateString() + " · "
      + (CREW_ROLE[String(s.role || "").toLowerCase()] ? t(CREW_ROLE[String(s.role).toLowerCase()]) : (s.role || "?")),
    CREW_OP[s.op] ? t(CREW_OP[s.op]) : String(s.op || ""), "c-dim"));
  }
  rows.push(el("div", { class: "c-dim small", text: F
    ? t("Frontier data, {a}: exact. The estimate from the balance (~) cannot tell market income at the carrier apart. Transfers move money, they are no gain or loss.", { a: age(F.age_s) })
    : t("Without EDMC's Frontier data (Companion API) only the journal: transfers and the estimate from the balance (~).") }));
  return rows;
}

function age(s) {
  if (s === null || s === undefined) return "?";
  return s < 3600 ? t("{n} min ago", { n: Math.max(1, Math.round(s / 60)) }) : s < 172800 ? t("{n} h ago", { n: Math.round(s / 3600) })
    : t("{n} days ago", { n: Math.round(s / 86400) });
}
