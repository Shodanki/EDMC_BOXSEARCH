// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// SPDX-License-Identifier: MPL-2.0
// Copyright (c) 2025-2026 Shodanki
//
// H1: pick the theme BEFORE any view module runs - some views read their
// colours (ui.js C) when they load. A classic script in <head>, so it runs
// first. The choice is per browser (localStorage), like the language; the
// "next" theme takes its accent colour from the browser too.
(function () {
  var THEMES = ["standard", "console", "industrial", "station", "next"];
  var theme = "standard", accent = null;
  try {
    theme = localStorage.getItem("fis.theme") || "standard";
    accent = localStorage.getItem("fis.accent");
  } catch (e) { /* private mode: the standard theme */ }
  if (THEMES.indexOf(theme) < 0) theme = "standard";
  var root = document.documentElement;
  root.setAttribute("data-theme", theme);
  if (theme === "next") {
    if (!/^#[0-9a-f]{6}$/i.test(accent || "")) accent = "#FF8A2A";
    var n = parseInt(accent.slice(1), 16);
    root.style.setProperty("--cyan", accent.toUpperCase());
    root.style.setProperty("--cyan-rgb", ((n >> 16) & 255) + ", " + ((n >> 8) & 255) + ", " + (n & 255));
  }
})();
