# regionmap - third-party code and data

* **Project:** EliteDangerousRegionMap by **Ben Peddell** (klightspeed) -
  <https://github.com/klightspeed/EliteDangerousRegionMap>
* **Licence:** MIT, "Copyright (c) 2020 Ben Peddell" - full text in
  [`LICENSE`](LICENSE), unchanged. It must stay with these files.
* **Game data:** the region map was traced from the galaxy map of Elite
  Dangerous, and the 42 region names are the codex names. Both are the work of
  Frontier Developments plc. The region boundaries were researched by the
  community on the Frontier forums.
* **Revision:** commit `6c1191a58e1e593966f44f16235ab39d1ad24d84` (12.05.2026),
  read on 13.11.2026. SHA-256:
  * `RegionMapData.py` `87cc4ee73fbe8a817dee334f2d0e9901fbd26c104db206b465cddb2a5eff2bba` (shipped **unchanged**)
  * `RegionMap.py` `8c9e54c559c47e4ad3d0513d00369f2108f489967331d299fc3cc4c1f9f2d3ea` (source of `__init__.py`)
  * `LICENSE` `f53e7fcde70b59ecfda402dac7bc35700c56f1472eec46bd26acc9bad06676b6`

## Changes

`__init__.py` is derived from `RegionMap.py`. The lookup arithmetic
(`findRegion`, `findRegionForBoxel`) is the same. What changed:

* the data is loaded lazily;
* there is a helper for the journal's `$Codex_RegionName_N;`;
* the original's EDSM lookup and command line are **left out**, so nothing in
  this folder goes to the network.

## Checked

* The 41 systems with a codex entry in the developer's own journals give the
  same region as the game wrote (13.11.2026).
* The import probe in CI: `find_region(0, 0, 0)` is Inner Orion Spur.

## Used for

The codex region of a target:

* in the overlay briefing (`REGION`);
* in the FIS BRIEFING, together with "new region" when the jump leaves
  yours;
* in the GALAXY focus.
