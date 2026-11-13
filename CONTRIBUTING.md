<!--
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
SPDX-License-Identifier: MPL-2.0
Copyright (c) 2025-2026 Shodanki
-->
# Development rules

Every change to SHBOXSEARCH and SHBOX FIS follows these rules. They come from
three places:

* the [listing standards of the EDMC plugin browser](https://github.com/EDCD/EDMC-Plugin-Registry/blob/main/docs/STANDARDS.md);
* EDMC's [plugin documentation](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md);
* the project's own promises to the community.

A change that breaks one of them is not merged.

The rules were checked against EDMC 6.1.2 on 13.11.2026. When EDMC releases a new version (pre-releases included), read its changelog and PLUGINS.md again. Then update this file and the plugin in time.

## 1. The game and the community services

* **Read and display only.** Nothing is sent to the game, no key presses, no input of any kind, nothing automated. That is Frontier's EULA.
* **One door to the internet:** every online request goes through `netgate.Gateway`. That covers:
  * one request at a time, with pauses per service;
  * Retry-After and rate-limit headers are followed;
  * at most 50 requests per service and UTC day (shared with the FIS);
  * the offline switch;
  * every attempt is logged.

  Never call `requests`, `urllib` or a socket to the internet anywhere else.
* **Local first.** Ask the network only for what the journal, the database and EDDiscovery's file cannot answer. Keep answers and do not ask twice.
* **Public APIs only, never scraping.** Use EDSM `api-v1`, the Spansh `api/...` endpoints and the GitHub REST API. Never parse a web page. A new service needs its API, its fair-use terms, a pause and a daily cap in `netgate.py`.
* **User-Agent:** EDMC's `config.user_agent` first, then `SHBOXSEARCH/<version> (+repository)`.
* There is no lookup of first discoverers at EDSM. Discovery comes from the commander's own journal.

## 2. EDMC's plugin rules

* **Entry points:**
  * `plugin_start3` returns quickly;
  * `plugin_stop` cleans up: it clears the overlay, closes the windows, stops the gateway and closes the database;
  * every hook catches its own errors and logs them, so nothing escapes to EDMC.
* **Only documented imports** from EDMC: `config` (for the plugin's own `shboxsearch_*` settings), `theme`, `myNotebook`, `l10n`, `monitor`, `companion`, `plug.show_error`, `timeout_session` and `ttkHyperlinkLabel`. Read `config` with `get_str` / `get_int` / `get_bool` and a `default=`.
* **Tk only on the main thread.** A background thread never touches a widget, a Tk variable or `after()`. It hands its update to `uithread._ui()`, which queues it and sends the one allowed call: `event_generate()` to the top-level window. While EDMC shuts down (`config.shutting_down`, a property) nothing is sent. `tests/ui_threads.py` checks this statically for every function a worker can reach, across all modules. Keep it green.
* **Never block the main thread.** Anything that may take more than a moment goes through `uithread._run_async`. That includes network requests, journal replays, reading EDDiscovery and scanning files. Hold the database lock only in short slices.
* **Logging:**
  * use the plugin's EDMC logger (`EDMarketConnector.<folder name>`), never `print()` in plugin code;
  * helper modules use `logging.getLogger(__name__)`, and `state.py` routes them to the plugin logger;
  * log messages are in English.
* The folder name stays importable (`SHBOXSEARCH`, no hyphen or dot), and every setting key starts with `shboxsearch_`.
* **Module names are shared by all plugins** (PLUGINS.md, "Common resources"). The plugin never puts its folder on `sys.path`; its modules import each other relatively, as members of the plugin's package (`from . import netgate`). The helpers keep a plain import only for running on their own (`if __package__: ... else: ...`). `tests/package_import.py` checks both of EDMC's ways to load a plugin.
* **Where code lives:** `load.py` is only the layer EDMC talks to. The shared state and settings are in `state.py`; each part of the plugin has its own module (journal hooks, planning, survey, cockpit, panel, windows, settings page). A new feature gets a new module. A name from another module is used as `module.name`, so tests can replace it and import cycles stay harmless.

## 3. Least privilege

* The release ZIP holds only what the plugin and the FIS run with. Tests, CI, development scripts, logs and the dotfiles are `export-ignore` (see `.gitattributes`). A new file that is not needed at run time gets the same treatment. Code that is no longer used is removed; git history is the archive.
* No new Python package without a reason. EDMC's bundled standard library plus `requests` is the plugin's world; the FIS needs the standard library only. Third-party code is shipped only when it is needed, unchanged where possible, with its own licence (see below).
* Files are read only where they belong: the plugin folder, the journal folder, EDDiscovery's database (read only) and, for the FIS, the plugin's own `shboxsearch_*` keys in EDMC's settings file. Nothing else on the PC is touched.
* **The FIS:**
  * By default it serves this PC only: it binds to 127.0.0.1 and accepts only a localhost Host.
  * The home-network mode is the user's choice. In that mode every request needs the access token.
  * The narrow firewall rule is created only after the user's explicit yes.
  * The FIS does not start with EDMC unless the user switches that on.
* No elevated rights, except that one firewall rule after the yes. No services, no autostart entries, no registry changes.

## 4. Licence

* Own code is under the **Mozilla Public License 2.0**. Every own file starts with the 5-line MPL header with SPDX identifier and copyright line (`#`, `//`, `;`, `rem` or `<!-- -->` as the file type needs).
* The notice **"Incompatible With Secondary Licenses" (MPL Exhibit B) is never used** in any file. Through it the code stays compatible with EDMC's GPL-2.0-or-later (MPL section 3.3).
* **Third-party parts** keep their own licence and file. They must be GPL-compatible: MIT, BSD, LGPL, GPL, MPL or Apache-2.0, never "no licence". Each part gets:
  * a `SOURCE.md` with origin, version and checksum;
  * a header naming the change;
  * a line in the README section *Third-party parts*.
* Frontier's data is credited as Frontier's. Data files of outfitting tools such as Coriolis or EDSY are not taken over.

## 5. Code standards

* **PEP 8** as EDMC checks it: `python -m flake8` with the project's `.flake8` (120 characters, third-party files excluded). CI runs it. New code adds no finding.
* **Complexity:** EDMC's limit is 15 (`--max-complexity 15 --select C901`). Every new function keeps it; the older functions above it (helper modules and the FIS, listed in `tests/complexity.py`) may not get more complex, and leave the list once they are split. CI enforces both.
* **Readable for a reviewer:** a docstring for every hook, every module and every public function you add or change. Comments explain *why*, not what. Keep files and functions small; new features go into their own module.
* **Splitting code without changing it:** a refactoring that only moves code is checked against the code before it - same tests, and where a window draws, the same widget calls with Tk replaced by a recorder.
* **Tests:** every fix comes with a test that fails without it, and every CI step stays green:
  * the module self tests;
  * `tests/*.py`;
  * `python -m unittest discover` in `FIS/`;
  * flake8 and `tests/complexity.py`.

  A change the browser shows is also checked in a browser.
* Python 3.13 is the interpreter EDMC ships (32-bit). Do not use language features newer than that.

## 6. Versions and releases

* **SemVer, strict:** `VERSION` in `state.py` (re-exported by `load.py`) and `__version__` in `FIS/fis/__init__.py` are the same `Major.Minor.Patch` (`tests/package_import.py` checks it). Fixes raise the patch version, features the minor version, and only fundamental changes the major version. Tags carry a leading `v` (`v4.10.1`); the registry's `pluginVer` does not.
* **One commit per fix or feature.** The message says what and why. The version bump and the README section *What changed* come last, in a release commit of their own.
* A release is merged to `main` first. Then it is tagged and published with the ZIP from `git archive` of the merge, with its SHA-256 and a VirusTotal check.
* **AI disclosure:** AI-assisted commits end with the `Co-Authored-By` trailer. Release notes end with the footer from [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md). `AI_TRANSPARENCY.md` and `ai-disclosure.json` are updated before any AI feature runs inside the plugin (none does today).

## 7. For the user

* No command-line parameters for users. Settings live in EDMC's preferences or on the FIS settings page; the FIS asks on its first start and remembers the answers in `fis.ini`.
* The FIS speaks English and German. Every new text gets both (`FIS/web/js/i18n.js`, checked by `test_i18n`).
* The user's data is never overwritten by an update:
  * the database;
  * `fis.ini`;
  * `favourites.json`, `lost_hidden.json` and `vehicle_tanks.json`;
  * the saved carrier data.
