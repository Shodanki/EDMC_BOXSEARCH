1. This Plugin comes with NO Warrantie what so ever!.
2. This Plugin is created via ChatGpt version 5 again we booth my make errors.
3. i still did not solved the theme aware issue so if you can create a fix i am happy to involve it.
4. Other then this i am happy if this works for you as for me future updates my come if i need something.
EDMC_SphereSurvey — README (v1.4.1)

A lightweight EDMarketConnector plugin to systematically survey all star systems in a spherical radius around your current location. It builds a worklist, selects the next target automatically, copies it to your clipboard for easy Galaxy Map search, and tracks progress to avoid duplicate jumps.

What changed vs prior drafts: This edition reflects the actual implementation in v1.4.1 — local‑first neighbour data, EDSM cube‑tiling fallback, no EDSM token required, clipboard post‑jump fallback, and persistent resume. (The earlier ideas for single‑hop filtering, CETI integration, and EDSM personal logs are not part of this version.)

Features

One‑click start: Build the nearby‑systems checklist from Local JSON (EDDiscovery/EDDicovery export) by default; if not available, use EDSM cube-systems tiling and compute the sphere locally from coordinates.

Progress tracking: Marks systems as visited on FSDJump/Location journal events; deduplicates by SystemAddress (id64) and name; persists queue & progress to state.json and restores on EDMC restart.

Auto‑target: Always shows the next system and copies its name to the clipboard. Includes a post‑jump fallback re‑copy to stay in sync after rapid double‑jumps or NavRoute delays.

Radius filter: User‑set radius (ly). Sorting is nearest‑first from the start system.

Local‑first data: Reads neareststars.json (EDDiscovery/EDDicovery) containing neighbour names and coordinates; distances are recomputed locally.

Online fallback (optional): Uses EDSM /api-v1/cube-systems with tiling (edge ≤ 200 ly) and filters by local distance. No API key required.

Theme‑aware UI: Uses EDMC’s themed myNotebook widgets — no hardcoded colours. “Next target” is a label to avoid white fields in dark themes.

Not included in v1.4.1: single‑hop/jump‑range filtering, CETI integration, and EDSM personal‑log filtering. These may be considered for a future release.

Requirements

EDMarketConnector 5.x+

Optional internet access to EDSM (only when using the online fallback)

Installation

Create folder: EDMarketConnector/plugins/EDMC_SphereSurvey/

Save load.py (v1.4.1) into that folder.

(Optional) Place your neareststars.json (EDDiscovery/EDDicovery export) in the same folder or note its path for Settings.

(Optional) Delete state.json to start fresh.

Launch EDMC.

Configuration (Preferences tab)

Enable EDMC_SphereSurvey: Master on/off for logic and event processing.

Debug logging: Adds verbose lines to EDMC logs (prefix <SHBOXSEARCH>).

Data source: auto / local / edsm

auto → prefer Local JSON if available, otherwise use EDSM cube‑tiling.

local → force Local JSON.

edsm → force EDSM cube‑tiling (no token required).

Local JSON (neareststars.json): File path to your EDDiscovery/EDDicovery export.

Default radius (ly): Sphere radius for new runs.

Auto‑copy next target: Keep clipboard synced to the next system.

Usage (Main panel)

Verify Enabled is checked.

Click Detect system (should show your current system). Set Radius (ly) and choose Source.

Click Start. The plugin builds the list; Next target appears and is copied to your clipboard.

Jump and explore as usual. On each FSDJump/Location, the plugin marks progress, advances the queue, and re‑copies the next target (with a short fallback re‑copy if needed).

Click Stop to pause (progress is preserved). Click Reset to clear state and state.json.

When the queue is exhausted the panel shows Queue size: 0. You can reset to begin a new survey.

How it works (technical)

Local JSON path: Parse EDDiscovery/EDDicovery neareststars.json → read neighbour Name/X/Y/Z → compute distance from center → filter ≤ radius → sort → deduplicate by id64/name → persist queue.

EDSM fallback path: Resolve center coords via /api-v1/system (by name or id64). Tile /api-v1/cube-systems (edge ≤ 200 ly) around the center to cover your radius → merge & deduplicate → compute distances locally → filter ≤ radius.

Recognition: On FSDJump/Location, mark current system visited by SystemAddress (id64) (preferred) and by name (fallback), then advance and copy next target. A post‑jump fallback re‑copies after ~1.5 s to defeat timing races.

Persistence: The queue, visited sets, and settings snapshot are stored in state.json and loaded on startup.

Notes & limits

EDSM sparsity: Some regions return few/no neighbours; use Local JSON for best coverage.

Large radii: EDSM tiling issues multiple cube queries; initial build may take longer for very large spheres.

No periodic refresh: The list is built at Start (or resume). To include newly discovered systems from external sources, rebuild the list (Start after Reset) or switch to Local JSON exports that include the new data.

Privacy

No credentials required. If you use EDSM fallback, only public proximity endpoints are called. The plugin stores only its own settings and state in EDMC’s config and its state.json file.

Support

Enable Debug logging and check EDMarketConnector-debug.log for lines beginning with <SHBOXSEARCH>.

Common fixes: ensure EDMC journaling is active; verify Local JSON path (or EDSM internet access); reduce radius for sparse regions.

Version history (recent)

1.4.1 — Post‑jump clipboard fallback; robustness for rapid double‑jumps; local‑first data; EDSM cube‑tiling fallback; persistence; themed UI.

1.4.0 — Switch to cube‑tiling only (no sphere endpoint); compute distances locally; local‑first workflow.

1.3.0 — Removed Spansh; stable clipboard; persistence; theme‑safe labels; EDSM public endpoints only.

1.2.0 — Added Local JSON provider and id64 name/coord resolution.

License: MIT © 2025
