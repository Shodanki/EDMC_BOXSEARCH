# SHBOXSEARCH v4.9

> **AI disclosure (Art. 50 EU AI Act):** developed with the help of the AI
> assistant Claude (Anthropic); every change is reviewed and tested in the game
> by the developer. The plugin and its FIS companion contain no AI system, send
> no data to any AI service, and their output is not AI-generated.
> Details: [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md) ·
> machine-readable: [ai-disclosure.json](ai-disclosure.json)

Systematic, exhaustive sphere survey for Elite Dangerous. EDMC plugin.

**SHBOX FIS** (since 4.4), a flight information system for a second screen,
tablet or phone - planet surface, system in 3D, galaxy in 2D and 3D, planet
info, atlas, ship status, carrier, mining and statistics - in the `FIS`
folder of this plugin. See [FIS/README.md](FIS/README.md) - with
screenshots (demo data).
**New in 4.10:** fewer galaxy map searches for every system no database
knows. Sector names are computed, so boxels in sectors nobody visited are
planned too, and hand-authored sectors (NGC 2232, Col 70 ...) under their
own names. Catalogue stars fill their number in a boxel, *list ends at*
takes the end of the galaxy map's list, and candidates EDDiscovery already
knows leave the queue - in the developer's sphere 1 902 probes became 856.
The briefing and the FIS name the codex region - see
[What changed in 4.10](#what-changed-in-410).

**Licence:** [Mozilla Public License 2.0](LICENSE) since 4.7 - use, change and
share it freely; whoever passes on a changed file of this project keeps that
file open under the same licence (files of your own next to it are yours).
4.6 and earlier were released under MIT and stay MIT. Third-party parts keep
their own licence: Three.js 0.170.0 (MIT, `FIS/web/vendor/three`),
Project Nayuki's QR Code generator (MIT, `FIS/fis/vendor`), EDTS's sector
name algorithm by Andy Martin (BSD 3-Clause, `edts_pgnames`) and Ben
Peddell's region map (MIT, `regionmap`) - origin and licence text in the
`SOURCE.md` / `LICENSE` files there; all of them in
[Third-party parts](#third-party-parts).

Repository: <https://github.com/Shodanki/EDMC_BOXSEARCH>

Provided **as is**. The plugin checks once a day whether a newer release is
tagged and says so - it never replaces its own files. Updating stays a
deliberate act, because the thing worth protecting here is a database that
grows over months, and a half-applied update in the same folder is the one
failure that actually hurts.

**Contents**

1. [Operation](#operation) - what you need, install, update, files, first
   start and maintenance, preferences, known limits
2. [Third-party parts](#third-party-parts) - what is shipped with it, what
   it reads and asks, Frontier's data
3. [How it works: the why and the maths](#how-it-works-the-why-and-the-maths) -
   names, gap logic, existence checks, sources, routing, fuel, learning
4. [Version history](#version-history) - every release, oldest first
5. [For maintainers](#for-maintainers) - releasing

---

# Operation

## What you need

| | | |
|---|---|---|
| **EDMC** (Elite Dangerous Market Connector) 5.10 or newer | required | the plugin runs inside it; tested against 6.1.2 / Python 3.13 |
| **Elite Dangerous: Odyssey** | required | the plugin reads its journals and status files |
| **EDDiscovery** | recommended | its system database is the local source: while it is current the plugin does not ask Spansh at all, EDSM once per shell (see [Fair use](#7-external-sources)). Open it now and then so its data stays current, then close it |
| **Python 3.11 or newer** (python.org) | for SHBOX FIS only | the flight information system runs on it; the plugin itself needs nothing beyond EDMC |
| **EDMCModernOverlay** | optional | for the cockpit overlay (route targets, surface compass, mining block) |

> **Updating from 4.0?** Replace the `.py` files and start EDMC - that is
> all. On the first start 4.1 repairs boxel records written under a wrong
> naming rule and replays your journals once in the background to fill the
> new per-body fields. See [What changed in 4.1](#what-changed-in-41).

## Install

1. Download this repository (green **Code** button -> **Download ZIP**, or
   `git clone`).
2. Copy the folder into EDMC's plugin directory and name it `SHBOXSEARCH`:

   | OS | Path |
   |---|---|
   | Windows | `%LOCALAPPDATA%\EDMarketConnector\plugins\SHBOXSEARCH` |
   | macOS | `~/Library/Application Support/EDMarketConnector/plugins/SHBOXSEARCH` |
   | Linux | `$XDG_DATA_HOME/EDMarketConnector/plugins/SHBOXSEARCH` |

   The `.py` files must sit directly in that folder, not in a subfolder.
3. Restart EDMC.

On first start the plugin reads your existing journals and builds its database.
That takes a few minutes with a long flight history; EDMC stays usable. Watch
the plugin's status line, or the EDMC log for `first-run import finished`.

No Python installation is needed - EDMC ships its own interpreter. There are no
third-party dependencies.

## Update

The plugin tells you when a release is newer than the one running:

```
update v4.1.0 available - click to open GitHub
```

Clicking opens the release page. Then:

1. Close EDMC.
2. Replace the `.py` files and the folders (`edts_pgnames`, `regionmap`,
   `FIS`) with the new ones. **Leave `shboxsearch.sqlite`
   alone** - that is your survey data.
3. Start EDMC.

The database migrates itself: new columns are added in place, nothing is
dropped. When an update adds new per-body data, the plugin replays your
journals once on its own (4.1 does); *Preferences -> SHBOXSEARCH -> Replay
journals* repeats that at any time and is safe to run as often as you like.
Since 4.6 the plugin copies the database to `shboxsearch.sqlite.schema<N>-<time>.bak`
before it changes the schema or repairs records (the last three are kept).

SHBOX FIS keeps running when EDMC is closed: after an update close its
window (or end `python -m fis`) so it starts with the new files. Keep
`FIS/fis.ini`, `FIS/favourites.json`, `FIS/lost_hidden.json` and
`FIS/vehicle_tanks.json` - your settings, favourites, hidden losses and the
tank sizes the FIS learnt.

## Files

All `.py` files go in the plugin folder. `shboxsearch.sqlite` is created
on first run and is **your data** - never overwrite it on an update.

| File | Lines | What it does | Depends on |
|---|---|---|---|
| `load.py` | 4715 | EDMC entry point: panel, windows, journal handling, all UI | all of the below |
| `sysdb.py` | 3133 | SQLite store: systems, bodies, boxels, hotspots, earnings, spheres | `procgen` |
| `sysroute.py` | 980 | In-system routing: Kepler positions, 2-opt tour, cost model | — |
| `boxelplan.py` | 999 | Sphere planner: gaps, probes, prospecting score, statistics, labels of named sectors | `procgen`, `sysdb` |
| `sources.py` | 776 | External data: EDDiscovery, Spansh, EDSM | `netgate`, `shells` |
| `netgate.py` | 474 | The one door to the internet: pacing, Retry-After, rate-limit headers, call log, self test | — |
| `shells.py` | 321 | Local-first: shells nearest first, coverage, 5-14 day validity, EDSM sphere cover, self test | — |
| `procgen.py` | 645 | Name ↔ id64 ↔ boxel maths, sector registry, computed sector names, named sectors over a boxel, self test | `edts_pgnames` |
| `deepspace.py` | 441 | Fuel model, tritium rings, carrier staging | — |
| `overlay.py` | 431 | Cockpit overlay through EDMCModernOverlay (optional) | — |
| `biopredict.py` | 204 | Genus prediction learned from your own samples | — |
| `surfacenav.py` | 493 | Surface compass: parked SRV, open samples, known points | — |
| `miningstat.py` | 337 | Mining block for the overlay: last rock, hold, rate, session, limpets | — |
| `journalscan.py` | 367 | Reading the journal files: last location and body, bodies approached, work timings (live and replay), fuel replay, self test | — |
| `edts_pgnames/` | | Sector names computed with EDTS's algorithm, hand-authored sector table (third-party, BSD 3-Clause, see its `SOURCE.md`) | — |
| `regionmap/` | | Codex regions of the galaxy (third-party, MIT, see its `SOURCE.md`) | — |
| `FIS/` | | SHBOX FIS, the flight information system (own Python process, see [FIS/README.md](FIS/README.md)) | the modules above |

Only `load.py` touches tkinter or the EDMC API; everything else is plain
Python with no third-party dependencies and can be run and tested on its own.
`python procgen.py` runs the maths self test and should print `failures: 0`.

### Suggested `.gitignore`

```
shboxsearch.sqlite*
__pycache__/
*.pyc
neareststars.json
survey_state.json
capi_fleetcarrier.json*
```

`neareststars.json` and `survey_state.json` are legacy import sources and
personal data - they belong on your disk, not in the repository. So does
`capi_fleetcarrier.json` (see below).

### Requirements

* EDMC 5.10 or newer (tested against 6.1.2 / Python 3.13)
* Elite Dangerous: Odyssey journals
* Optional: EDDiscovery, for a fast local system database
* Optional, for the FIS: Python 3.11 or newer

### Uninstall

Delete the folder. `shboxsearch.sqlite` goes with it, so copy it out first if
you want to keep the survey record.

## First start and maintenance

**No Python installation is required.** EDMC ships its own interpreter and the
migration runs inside the plugin.

1. Copy the `.py` files into
   `%LOCALAPPDATA%\EDMarketConnector\plugins\SHBOXSEARCH\` (see
   [Install](#install) at the top). If you come from v3 and still have
   `neareststars.json` and `survey_state.json`, leave them in place for the
   first import; they are read once and never modified.
2. Restart EDMC.

On first start the **initial import runs automatically in the background**:

* `neareststars.json` and `survey_state.json` are read (never modified),
* every existing journal is replayed to rebuild the scan state,
* a marker is then stored so it never runs again unasked.

Progress appears in the plugin status line (`first-run import: journals`,
`journals 12/340`) and in full in the EDMC log. With years of flight history
this can take a few minutes; EDMC stays usable throughout.

3. Open Preferences → SHBOXSEARCH and check:
   * *Journal folder* — must show a path, not `NOT FOUND`
   * *First import* — shows the timestamp of the run
   * *EDDSystem.sqlite* — set the path via `...` if needed
   * per-source status — `ok`, or the reason it is not
4. Press **Self test**. It verifies the procgen maths and writes the result to
   the EDMC log (`selftest | failures: 0`).
5. Fly to the start system, pick a radius, press **Start**.

### Maintenance buttons

| Button | Effect |
|---|---|
| **Run first import** | repeats the whole initial import (idempotent, loses nothing) |
| **Replay journals** | re-reads the journals only |
| **Import JSON** | re-reads the two JSON files only |
| **Export plan (CSV)** | writes the full target list |
| **Export boxel prefixes** | writes the prefix list for the galaxy map search |
| **Self test** | verifies maths and reports database statistics |

The plugin imports the old JSON files itself on first start. The 4.0 helper
scripts `migrate.py` and `diagnostics.py` were removed in 4.10.1; they stay in
the git history.

## Preferences

**Survey** — radius (50/100/150), active mass codes, probe depth above the
boxel maximum, empty probes on/off, queue outstanding scans on/off, jump range,
carrier start on/off, statistics block on/off. Shows the remembered carrier and
the last six surveyed spheres.

**Data sources** — EDDiscovery / Spansh / EDSM individually switchable, path to
`EDDSystem.sqlite` with a file picker, per-source status line.

**Automatic harvesting** — read NavRoute, read target selection, auto-copy.

**Maintenance** — run first import, replay journals, import JSON, export plan
as CSV, export boxel prefixes, self test, database statistics.

## Preferences layout

Two columns instead of one stack, because the full set ran off the bottom of a
1080p window. Left holds everything about the survey itself (sphere, mass
codes, what counts as needing a visit); right holds sources, harvesting and
window behaviour; maintenance buttons run full width in a 3x2 grid underneath.

## Known limits

* **Sectors without a name mapping.** The plugin learns the sector name ↔
  sector index mapping from observed systems; Frontier's sector name generator
  is not reimplemented. One known system per sector is enough. At 150 ly a few
  neighbouring sectors are typically missing at first — an EDSM/Spansh query or
  a single jump there resolves it. The count appears in the plan summary.
* **Mass code h** has culling gaps; the gap logic does not apply there.
* **Spansh** lags by up to 48 hours.
* **Position uncertainty** for unconfirmed candidates is half the boxel space
  diagonal (a ±9 ly, b ±17 ly, c ±35 ly, d ±69 ly). After the first jump the
  position is exact.
* The EDDiscovery source supplies names and exact coordinates, but no
  SystemAddress. Catalogue numbers (HD, HIP …) are packed in a format that is
  not decoded yet and still come from EDSM/Spansh.
* Named "... Sector" regions (NGC 2232 Sector, Cephei Sector …) are
  hand-authored and have their own boxel origin; the planner's grid does not
  apply to them, so they are flown but never probed.

---

# Third-party parts

What in this project comes from others, and how it is used. To run the
plugin you need nothing of it beyond EDMC and the game.

**Shipped with SHBOX FIS, unchanged, under their own licence:**

| Part | Licence | Where | Used for |
|---|---|---|---|
| Three.js 0.170.0 (three.js authors) | MIT | `FIS/web/vendor/three` - `three.module.js`, `addons/controls/OrbitControls.js` | the 3D views, also offline |
| QR Code generator by Project Nayuki | MIT | `FIS/fis/vendor/qrcodegen.py` | the QR code on the FIS settings page |

**Shipped with the plugin, under their own licence** (since 4.10):

| Part | Licence | Where | Used for |
|---|---|---|---|
| Sector name algorithm and hand-authored sector table from **EDTS** by Andy Martin (with research by CMDR Jackie Silver; CMDR furrycat) | BSD 3-Clause | `edts_pgnames/` - derived and modified (ported to the plugin's sector indices); the tables unchanged | sector names where no system is known yet; boxels inside and at the edge of named sectors ([Named sectors over the grid](#named-sectors-over-the-grid)) |
| **EliteDangerousRegionMap** by Ben Peddell (klightspeed) | MIT | `regionmap/` - `RegionMapData.py` unchanged, `__init__.py` derived (without the original's EDSM lookup) | the codex region in the briefing and in the FIS |

Origin, version and checksum are in the `SOURCE.md` next to each; the licence
texts stay with the files (`LICENSE` / `LICENSE.txt` there, the header of
`qrcodegen.py`). The names, the name fragments, the region map and the
region names are Frontier's game data (see *Frontier's data* below).

**Ideas, not code:** the [systematic-boxel-survey](https://github.com/Oberonmeister/systematic-boxel-survey)
project by Oberonmeister documented that named sectors overlap procedural
boxels and that one physical boxel can carry two labels. The plugin's own
handling of that is described in *How it works*. The project has no
licence, so none of its code or text is used.

**Used, not included** - no code of these is part of this project:

* **EDMC** (Elite Dangerous Market Connector) - the host the plugin runs in,
  through its plugin interface; it also hands over Frontier's Companion API
  answer for your fleet carrier.
* **EDMCModernOverlay** (or the older EDMCOverlay) - optional; the cockpit
  overlay is drawn through its `edmcoverlay` interface when it is installed.
* **EDDiscovery** - its system database `EDDSystem.sqlite` is read as the
  local source; nothing is written to it.
* **Spansh** and **EDSM** - asked over their public web interfaces, in shells
  and only when needed, at most 50 requests per service and UTC day, one at a
  time through one polite gateway (`netgate.py`). The rules are in
  [External sources](#7-external-sources) under *Fair use*.

**Frontier's data.** Elite Dangerous is a game by Frontier Developments plc.
The plugin and the FIS read the game's own journal and state files on your PC
(`Status.json`, `NavRoute.json`, `Cargo.json`, ...) and, through EDMC, the
Companion API answer for your carrier. They only display: nothing is sent to
the game and nothing is automated. SHBOXSEARCH is a free fan project, not
affiliated with or endorsed by Frontier.

**Ship data.** Ship values (mass, tank, jump range, cargo) come from the
game's own `Loadout` event; no data files of outfitting tools such as Coriolis
or EDSY are included.

---

# How it works: the why and the maths

Goal: completely explore a chosen radius (50 / 100 / 150 ly) around a start
point — find every system, fly there, scan it and map it, with particular
weight on systems that appear in no public database.

Tested against EDMC 6.1.2 / Python 3.13.

## 1. Why this is necessary

EDSM, Spansh, EDAstro, EDDB, Inara and the EDDiscovery database are all
**aggregators of EDDN uploads**. They only know what players have uploaded.
Frontier operates no public galaxy API, and the Stellar Forge has not been
reimplemented.

That makes the **game client the only authority on which systems exist**. A
genuinely complete sphere survey has to ask it.

SHBOXSEARCH does exactly that: it derives from the procedural naming rules
which systems *must* exist, and lets the client confirm them.

## 2. How a system name is built

```
Synuefe   VA-I   b2   -1
   |        |     |    |
   |        |     |    +--  n2: running number inside the boxel, starts at 0
   |        |     +-------  mass code b + high part of the boxel number
   |        +-------------  letters = low part of the boxel number
   +----------------------  sector, a 1280 ly cube
```

The maths:

```
boxel id = n1·26³ + L3·26² + L2·26 + L1
boxel id = bx | (by << 7) | (bz << 14)          (7 bits per axis)
boxel size = 10 · 2^masscode  ly                (a=10 … h=1280)
```

The same information sits in the `SystemAddress` (id64):

```
[3 bit masscode][14-mc bit Z][13-mc bit Y][14-mc bit X][n2][9 bit body id]
```

Verified against `Eol Prou RS-T d3-94` (Colonia, id64 3238296097059) and
against every procgen system in the supplied journals and JSON files —
**no mismatches**.

Consequence: any name yields a position accurate to the boxel size, and any
id64 yields the full name back - where the boxel has only one name (see
below).

### Sector names, computed (since 4.10)

Up to 4.9 the plugin learnt the name of a sector from the first system it
saw there, so boxels in a sector without any known system could not be
planned. Since 4.10 the name is computed from the sector's place in the
128 x 128 x 128 grid with **EDTS's algorithm** (Andy Martin, BSD 3-Clause,
in `edts_pgnames/` - see [Third-party parts](#third-party-parts)). A name
the plugin saw itself still comes first. Checked against EDDiscovery's
database: 399 013 procedural systems from all over the galaxy, all correct.

### Named sectors over the grid

About 470 **hand-authored sectors** - *Col 285 Sector*, *NGC 2232 Sector*,
*Col 70 Sector* ... - are spheres laid over the grid. A star inside one is
named after the sphere, with boxel letters counted from the sphere's own
corner. The physical boxel and the number `n2` stay the same; only the
label changes:

```
Pyurks FH-J d10-0  and  NGC 2244 Sector GW-M d7-0  ->  same boxel, n2 = 0
```

Where the surface of such a sphere cuts a boxel, its systems carry either
label, depending on where each star lies. The planner therefore:

* names a boxel that lies inside a sphere only after the sphere. Before
  4.10 such boxels got procedural names the galaxy map never finds - in a
  test sphere inside NGC 2232 Sector that meant 540 useless probes and no
  gap found;
* counts `n2` across all labels of a cut boxel, so a gap is a gap whatever
  the name of its neighbours;
* tries the label of the boxel's centre first, or a label it has already
  seen there; *not there* under one label brings up the other, and only
  when both are ruled out is the number gone. The probe window says
  `edge  also named: ...`;
* closes a cut boxel only when every label's list was seen to its end.

An id64 alone gives a name only where the boxel has one label; at a
sphere's edge the plugin no longer guesses. The idea of keeping the
physical boxel apart from its labels comes from the
[systematic-boxel-survey](https://github.com/Oberonmeister/systematic-boxel-survey)
project (Oberonmeister), which documented the *Pyurks / NGC 2244* case. No
code or text of it is used - it has no licence.

### Catalogue stars hold a number too (since 4.10)

Every system has an **id64** that names its boxel and its number `n2`,
whatever the system is called. Real stars from catalogues keep their
catalogue name but still fill a number of their boxel:

```
Synuefe RH-U c19-   galaxy map lists 1, 2, 3 ... 21 - no "-0"
HIP 33254           id64 84791923370 = slot 0 of Synuefe RH-U c19
```

So a missing `-0` (or any missing number below the highest one) is not a
gap and not the end of the boxel. Since 4.10 the plugin counts the numbers
of a boxel by **id64** as well as by name, so a catalogue star fills its
slot. EDDiscovery's file holds the id64 of every system (its `edsmid`
column, in the files EDDiscovery builds from Spansh's data); the plugin
takes it only where the position lies inside the boxel that number names.

### Candidates looked up in EDDiscovery by id64 (since 4.10)

A boxel of mass code c is 40 ly wide; one that meets the edge of a 50 ly
sphere reaches up to 70 ly from its centre. EDDiscovery is read only to the
radius, so up to 4.10 most "gaps" were systems EDDiscovery knew - just
outside it. In the developer's sphere 945 of 950 gaps were such systems.

Since 4.10 every plan looks its candidates up in EDDiscovery's file by
id64 - local, read only, by primary key, no network. What is there is stored
with its position and the candidate is gone; a boxel whose maximum rises
that way gets its next probes looked up too (three rounds at most). The
same sphere then held 939 candidates instead of 1 859, and 5 gaps instead of
942: the 5 are systems really in no database.

A sphere restored at EDMC start reads EDDiscovery's file again once after
the update to 4.10 (the rows read before carry no id64), and afterwards
whenever its last reading has expired - so an old sphere plans on the same
data as a new one.

## 3. The gap logic

Within a boxel, `n2` runs **contiguously from 0** (true for mass codes a–g;
mass code h has culling gaps, which is why h is off by default). A number
can carry a catalogue name instead of the procedural one - see
[Catalogue stars hold a number too](#catalogue-stars-hold-a-number-too-since-410).

Three kinds of candidate follow from that:

| Kind | Meaning |
|---|---|
| **gap** | `n2` missing between 0 and the known maximum → almost certainly exists, but is in no database |
| **probe** | `n2` above the known maximum → finds the end of the boxel |
| **empty** | boxel with no known system at all → one lookup on `-0` decides whether it holds any stars |

## 4. Gap logic, re-checked

Verified against the current database:

```
boxels total: 44 | contiguous: 18 | with gaps: 26 | missing n2 values: 231

Synuefe KV-M b40   missing [0, 1, 2, 3, 4]  (highest known 5)
Synuefe MG-L b41   missing [0, 1, 2, 3, 4]  (highest known 5)
Synuefe OB-L b41   missing [2]              (highest known 4)
```

Those 231 names are systems that must exist - `n2` runs contiguously from 0 -
and that no database has. The negative cache is still empty because none have
been checked yet, which is consistent: nothing has been ruled out because
nothing has been looked at. The logic is doing what it should; it just needs
the galaxy map work to convert candidates into finds.

## 5. Existence checks without guesswork

**There is no journal event that lists nearby systems.** Every one of the
250-plus events in the Odyssey journal schema was checked against
`jixxed/ed-journal-schemas`; the only ones that ever carry a system name are
`FSDJump`, `Location`, `CarrierJump`, `CarrierLocation`, `FSDTarget`,
`StartJump`, `NavRoute`, `Scan`/`FSS*`/`SAA*`, `CodexEntry` and the
`Destination` field of `Status.json` — all of which this plugin already reads.
Nothing enumerates what is around you. The galaxy map remains the only oracle,
so the job is to ask it as few times as possible.

### The cheap path: one search per boxel

Galaxy map search matches on **prefixes**. Instead of testing
`Synuefe SH-N a6-2`, then `-3`, then `-4`, you paste `Synuefe SH-N a6-` once
and the result list shows every system that boxel contains.

That is what the probe bar is built around:

| Button | What it does |
|---|---|
| **prefix** | copies `Synuefe SH-N a6-` — one paste lists the whole boxel |
| **list ends at [n]** + **list end** | type the highest number the list shows (the field starts with the highest one the plugin knows) → the boxel ends there, every probe above it goes at once (since 4.10; was **boxel done**) |
| **not there** | a single name is missing → above the highest known number it closes the boxel from there up; below it, only that name goes (a catalogue star holds the number) |
| **later** | move this boxel to the back |

**list ends at** also works when the list is longer than what the plugin
knows: type `21` where it knew `19`, and `-20` and `-21` become certain
gaps - they exist, and no database has them. A number smaller than one the
plugin knows is refused: the list was cut off, scroll it to its end.

Any system you click in that result list sets it as target, which fires
`FSDTarget` and writes `Destination` — the plugin picks both up on its own, so
new finds land in the database without you typing anything. Since 4.10 that
takes the name out of the queue wherever it stands, not only at the head:
work the list from top to bottom, the window shows the next open one.
Plotting a route there also writes its exact position (`NavRoute`).

The probe queue is grouped **per boxel**, not by raw distance, so you work one
search at a time instead of hopping between boxels:

```
Synuefe SH-N a6-2   Synuefe SH-N a6    5.0 ly
Synuefe SH-N a6-3   Synuefe SH-N a6    5.0 ly
Synuefe OB-P a5-2   Synuefe OB-P a5    5.9 ly
Synuefe OB-P a5-3   Synuefe OB-P a5    5.9 ly
```

The probe line shows how many candidates the current boxel still has, so you
know what a single **list end** is worth.

**What this changes in practice.** At r=50 ly a sphere holds roughly 800 open
candidates spread over about 600 boxels. Candidate by candidate that is 800
searches. Prefix plus **list end** turns it into about 600 — and every boxel
that turns out empty is retired by one click instead of two or three.

### Prospecting: which boxel first

600 unprobed boxels is a lot of searches, so they are not worked in plain
distance order. Each boxel gets a score from two things that can actually be
measured — no model of the galaxy involved:

1. **Neighbourhood density.** The Stellar Forge places stars by mass density,
   so a boxel surrounded by populated boxels is far more likely to hold
   something than one sitting in a void. Counted over the 26 adjacent boxels.
2. **Source disagreement.** A system that only one of the three databases
   knows is a symptom of thin reporting — and thin reporting is exactly where
   undiscovered systems survive. Counted over the same neighbourhood.

The queue then sorts by **distance divided by promise**, so a boxel twice as
far but three times as likely comes first:

```
probe  Synuefe SH-N a6-2    5.0 ly  score 2.33
probe  Synuefe OB-P a5-2    5.9 ly  score 2.64
empty  Synuefe SK-I b2-0   13.9 ly  score 3.73   <- jumps the queue
probe  Synuefe UF-I b2-2   18.5 ly  score 4.64
```

The probe line shows it as plain words: `odds high` / `fair` / `low` / `void`.
A boxel scoring `void` has no known system anywhere near it and is almost
certainly empty — worth leaving for last.

### Reading the source coverage

```
sources: EDDiscovery 412, Spansh 425, EDSM 422 | only one knows it: 11 (9%)
promising boxels: 139  (top: Synuefe UF-I b2 4.6, Synuefe TF-I b2 4.6, ...)
```

Three databases that agree closely means the region is well reported and the
remaining unknowns are mostly in genuinely unprobed boxels. A disagreement rate
above 15% flags the opposite — the plugin says so explicitly:
`thin reporting here - good odds for undiscovered systems`. That is the cue to
probe hard here before moving the carrier.

## 6. Automatic harvesting

These channels run in the background without any action from you:

| Source | What it yields | Accuracy |
|---|---|---|
| `FSDJump` / `Location` / `CarrierJump` | name, id64, exact coordinates | exact |
| **`NavRoute`** | **every hop of a plotted route** with name, id64, exact position and star class | exact |
| `FSDTarget` | name + id64 of any targeted system | existence proven |
| `Status.json` → `Destination` | id64 of any selected target; the name is rebuilt from it | existence proven |
| `FSSDiscoveryScan` / `FSSAllBodiesFound` | body count, FSS completeness | — |
| `Scan` | body kind, class, `WasDiscovered`, `WasMapped` | — |
| `SAAScanComplete` | mapped bodies | — |
| `SAASignalsFound` / `FSSBodySignals` | bio and geo signals, genus | — |
| `ScanOrganic` | samples analysed | — |

**`NavRoute` is the strongest lever.** The in-game route planner works against
the real galaxy. Plot a route across the sphere and dozens of systems land in
the database with exact coordinates — regardless of whether anyone ever
uploaded them. One action, a large haul.

## 7. External sources

| Source | Priority | Notes |
|---|---|---|
| **EDDiscovery** (`EDDSystem.sqlite`) | 10 | local, no rate limit, very complete. Found automatically under `%LOCALAPPDATA%\EDDiscovery`. The current EDD layout (`SystemTable` + `Sectors` + `Names`, names packed into `nameid`, catalogue names such as `HIP 31330` included) is decoded directly; older layouts fall back to runtime detection. The coordinate scale is verified against the system you are in; the status line reports `verified` or `unverified`. EDD only needs to have been run once with its system database downloaded; it may be running at the same time. |
| **Spansh** | 20 | `POST /api/systems/search`, paged at 500. Index is rebuilt daily from the galaxy dump → up to 48 h behind. |
| **EDSM** | 30 | `sphere-systems` with `minRadius`/`radius`, 100 ly cap. Shells beyond 100 ly are covered by a few 100 ly spheres and cut back to the shell. Leaky-bucket rate limit, followed through its headers. |

**Fair use.** EDSM and Spansh are community services under heavy load; the
plugin asks them as gently as it can.

*Local first, in shells.* When you start a survey, the EDDiscovery file
(local, no network) is read for the whole sphere. EDSM and Spansh are asked
in shells around the centre, nearest first - 0-25, 25-50, 50-75, 75-100 ly
and so on - and both get exactly the same shell. The next shell is only
fetched when it is needed: when you come within 10 ly of the edge of what
has been fetched, or when nothing is left to fly to inside it. The planner
plans only inside the fetched shells, so it never sends you to a system the
next shell would show as known (the statistics window says how far the
online data reaches). A fetched shell is remembered per service for 5 to 14
days, the exact time drawn at random so that many installations do not ask
again at the same moment; a shell lying 90 % inside remembered ones - also
from an earlier survey nearby - is not asked again. Restarting EDMC asks
nothing. *reload online data* in the statistics window asks again on
purpose, paced like everything else. With both online sources switched off
or unreachable, the plan uses the local data for the whole sphere.

*EDDiscovery first.* EDDiscovery's system database is a copy of Spansh's
galaxy dump. When it was updated within the last two days, Spansh is not
asked at all - the same systems are read from the local file instead, shell
by shell; EDSM is still asked, because not everyone reports to every
network. Tip: open EDDiscovery once before you start a survey (it fetches
the latest changes), then close it - while it runs, its file can be locked.
The plugin notices a locked file and reads it again later.

*FIS.* The flight information system asks Spansh only when you click *online*
at a favourite carrier (where it was last reported), through the same
gateway and daily cap, at most once per carrier every six hours.

*Route check.* When you plot a route of two jumps or more through space no
source was asked about (outside the fetched shells), its systems are checked
once: first in EDDiscovery's file (local), then the rest - at most 40 - with
ONE EDSM request by name, through the same gateway, daily cap, offline switch
and EDSM switch. Every system asked is remembered for 14 days, so plotting
the same route again asks nothing, and the briefing can tell *known* from
*in no database (checked: EDSM)* there instead of *not checked*. A single
jump is never checked.

*Limits.* At most 50 requests per service and UTC day (a 50 ly survey needs
about five), at most 20 Spansh pages (10 000 systems) per shell. The
statistics window shows *external today: EDSM n of 50 · Spansh n of 50*.
*offline* in the plugin's settings sends nothing at all - not even the
update check.

*One polite gateway.* Every request goes through `netgate.py`:

* one request at a time, never in parallel, with a pause between two requests
  to the same service (EDSM 2 s, Spansh 1 s);
* EDSM's rate-limit headers are followed - when few requests are left before
  its reset, the pauses grow; at zero, EDSM is left alone until the reset;
* HTTP 429/503: the wait from `Retry-After` (or 5 s, 10 s), at most three
  tries; then the service is left alone until EDMC restarts. A wait longer
  than two minutes is not slept through - the service rests until then;
* the User-Agent names the plugin version and this repository;
* every request is logged with time, status and duration in the database
  (table `external_calls`, kept 30 days) and summed up in the EDMC log.

Deliberately **not** used:

* **EDDN live stream** — would need `pyzmq`, which EDMC does not ship; hit rate
  in a remote sphere is effectively zero.
* **Spansh galaxy dumps** — hundreds of gigabytes, not viable inside a plugin.
* **`ImportStars.txt`** as a bulk existence oracle — elegant in theory,
  unreliable since Odyssey, and it overwrites the real visited-stars cache.
  Too risky for data integrity.
* **Frontier cAPI** — commander, ship and station data only.

## 8. Data integrity

Every coordinate carries a quality level. **A lower-quality write never
overwrites a higher-quality one.**

```
40  JOURNAL    FSDJump / Location / NavRoute        exact, game client
30  EXTERNAL   EDSM / Spansh / EDDiscovery          exact, community
20  CONFIRMED  FSDTarget / Destination              existence proven
10  ESTIMATE   derived from name or id64            boxel centre
 0  UNKNOWN
```

No API and no estimate can degrade data you flew for. A confirmed find
automatically clears any stale negative-cache entry for that name.

Everything lives in `shboxsearch.sqlite` in the plugin folder (WAL mode). The
legacy `neareststars.json` and `survey_state.json` are **read only** during
import and left untouched.

Before an update changes the database layout or repairs stored data, the
plugin first copies the database to `shboxsearch.sqlite.schema<N>-<time>.bak`
in the same folder (the newest three copies are kept). To go back, close EDMC
and rename a copy to `shboxsearch.sqlite`.

When EDMC is logged in to Frontier, it fetches your fleet carrier from the
Companion API (at most every 15 minutes) and hands it to plugins. The plugin
keeps the latest answer as it is in `capi_fleetcarrier.json` in the plugin
folder - nothing is sent anywhere. SHBOX FIS reads it for what the journal does
not say: the goods in the carrier's hold, above all the tritium.

## 9. The two work queues

There are two, because these are two different activities.

**Fly** — go there and work the system:

| Kind | Meaning |
|---|---|
| `new` | known system inside the sphere, never visited |
| `scan` | visited, but the FSS sweep is incomplete |
| `dss` | body with a bio signal or of value, not yet mapped |
| `bio` | bio signal present, no sample taken yet |

**Probe** — check in the galaxy map: `gap`, `probe`, `empty`.

Ordering: distance in 5 ly bands first, priority within a band. That keeps the
flight path short without letting outstanding work rot.

### Names without a dash: `Synuefe XV-C d12`

Up to 4.0 this section claimed that such a name means "the boxel holds exactly
one system". **That was wrong**, and 4.1 fixes it.

The boxel number has a high part `n1` and Frontier simply leaves out `0-` when
`n1` is zero. `Synuefe XV-C d12` is system **n2 = 12** of boxel `XV-C d`, and
that boxel can hold `d0`, `d1`, `d2` … like any other. The game says so
itself: the SystemAddress of `Synuefe XV-C d12` (422810994947) decodes to
n2 = 12, and all 58 such names with a known SystemAddress agree. A plain
example in the data: `NGC 2232 Sector AQ-Y d10`, `d11`, `d13`, `d14`, `d15`,
`d16`, `d19` are seven systems in one boxel - and `d12`, `d17`, `d18` and
`d0` … `d9` are real gap candidates.

What the old reading broke, and what 4.1 does about it:

| Problem in 4.0 | 4.1 |
|---|---|
| Probes for n1 = 0 boxels were written `XV-C d-3`, a name that cannot exist | written `XV-C d3` |
| Such boxels could be closed by a galaxy map search that never had a chance | records rebuilt once on start |
| `XV-C d12` closed the unrelated boxel `XV-C d12` (`d12-0`, `d12-1` …) | records rebuilt once on start |
| Gaps below a dash-less name were never proposed | planned like any other boxel |

The search prefix for an n1 = 0 boxel is `Synuefe XV-C d` (no dash). The
galaxy map then also lists `XV-C d1-…`, `d2-…` - those belong to other boxels,
so count only the names without a dash. The probe window says so.

n1 = 0 occurs in the bottom two boxel layers (lowest z) of every sector, and
always for mass code h.

## 10. In-system routing

Arriving in a 40-body system, which order do you fly it in? The journal has
everything needed to answer that properly.

### The data is there, and it is exact

Every `Scan` event carries a full set of Kepler elements. Measured across the
supplied journals:

| Field | Present |
|---|---|
| `SemiMajorAxis`, `Eccentricity`, `OrbitalInclination` | 100% |
| `Periapsis`, `AscendingNode`, `MeanAnomaly`, `OrbitalPeriod` | 100% |
| `Parents`, `DistanceFromArrivalLS` | 98% (the exception is the arrival star, which is the origin anyway) |

That is enough to place every body in real 3D space instead of sorting by
radial distance. It matters: two moons can both read "1090 LS" and still sit
nowhere near each other, while a planet at 1666 LS and one at 1090 LS can be
neighbours if they are on the same side of the star.

Positions are resolved recursively through the `Parents` chain — a moon
relative to its planet, the planet relative to its star — and then shifted so
the **arrival star** is the origin. That last step is essential: in a binary
system the star you drop out at orbits a barycentre thousands of light seconds
away, and without the shift the whole system comes out wrong.

**Verified against the game's own figures.** Comparing the computed radius of
each body with the `DistanceFromArrivalLS` the game reports:

| System | Bodies | Mean error | Worst |
|---|---|---|---|
| Synuefe TH-J b42-5 | 40 | 0.10% | 0.9% |
| Synuefe VC-J b42-3 | 33 | 0.18% | 1.0% |
| Synuefe AH-X b20-0 | 41 | 1.00% | 7.6% |

The larger error in the third is a binary with a distant barycentre, where a
few bodies were scanned at different orbital epochs. Still well inside what
route ordering cares about.

### The route

Nearest neighbour builds a first tour, then 2-opt removes the crossings. Moons
are clustered with their planet, since they sit a few light seconds apart and
splitting them is always a loss. For the 10 to 40 stops a system has this runs
in well under a millisecond.

```
Synuefe VC-J b42-3: 29 stops, 11408 LS, about 82 min
 1. (main star)             0 LS  + 1 min
 2. 2 e                  1666 LS  + 9 min
 3. 2                       7 LS  + 2 min   DSS, bio x2
 4. 2 b                     3 LS  + 1 min
 5. 2 a                     1 LS  + 1 min
 ...
```

By default only bodies that still need something are routed — DSS outstanding,
bio signals unsampled, first discovery. A preference switches to routing every
body. The run starts at the arrival star, so its start is a deliberate step;
*start the route at the arrival star* switched off leaves it out and the
route begins with the first planned body (the FIS follows the same setting).

### The route window

**route** opens a separate window with the full list. Copy and paste has no
place here: bodies are picked in the system map, not typed. Only the external
jump target is ever copied, from the main panel.

The list is built to be read at a glance while flying:

```
Synuefe AH-X b20-0   32 of 32 stops left   16 planetary systems
97391 LS remaining, roughly 178 min

     A
[ ]   1. A                      0 LS   1 min
->  A 1
[ ]   2. A 1                    8 LS   2 min   DSS, High metal content body
->  AB 1                9 bodies    372 LS transit
[ ]   4. AB 1                 372 LS   5 min
[ ]   5.    AB 1 a              1 LS   1 min
[ ]   6.    AB 1 b              2 LS   1 min
...
->  AB 3                2 bodies   1787 LS transit
[ ]  14. AB 3                1787 LS   9 min
[ ]  15.    AB 3 a              2 LS   1 min
```

* **A switch to another planetary system gets its own header** in a larger bold
  font, with an arrow, the number of bodies waiting there and the transit
  distance. That switch is what costs real time — dropping out of orbital
  cruise, crossing thousands of light seconds, dropping back in — and it was
  the thing a flat list hid completely.
* **Moons are indented and set one size smaller** than their planet, so nine
  moons of `AB 1` read as one block instead of nine equal rows.

#### Grouping is by name, not by parent

Moons frequently orbit an unnamed barycentre between themselves, and those
barycentres are usually never scanned — so the `Parents` chain has holes.
Measured on real data, grouping by parent split the ten moons of `AB 1` into
six separate "systems" and produced a route that bounced between them.

Frontier names bodies strictly hierarchically (`AB 1 d` is moon `d` of planet
`AB 1`), so the name is the reliable source. Everything up to the first single
lower-case token is the planetary system. That took the same system from **22
groups down to 16** and put the nine moons of `AB 1` into one consecutive block.

### The system map

The window carries a top-down map drawn on a plain tkinter Canvas — no extra
dependency, redraws in about a millisecond. The projection is the X/Z plane
seen from galactic north, the same orientation as the in-game system map.

Distances in one system span four orders of magnitude (a moon 2 LS out, a gas
giant 4000 LS out), so the **radius is drawn on a log scale**: angles are exact,
only radial spacing is compressed. Ticked-off stops turn hollow with a dashed
leg, arrows mark the jumps between planetary systems, and range rings give the
scale. **map** toggles it.

### Feedback from the journal

Ticking stops off by hand while flying is busywork, so the plugin does it
itself. `ApproachBody`, `Touchdown`, `SAAScanComplete` and `ScanOrganic` all
name the body directly:

```
route | reached AB 1 c (approach), 5 of 32 done
route | reached AB 1 c (mapped), 6 of 32 done
```

The manual checkbox stays for what the journal cannot see — a body you looked
at and decided to skip.

From the first tick the plugin also measures itself, leg by leg: the time
from one tick to the next against the planned time of the stop just reached
(taken at the tick, while it still holds its work - mapping, samples). The
median of those ratios gives an honest correction for the rest:

```
actual pace 1.4x the estimate - remaining is more like 61 min
```

The median keeps one odd leg - repairs, a landing, a body mapped on the
side - from deciding it; it needs two legs. That line appears in the window
header and in the log. It is the only check the plugin can make on its own
model without guessing, and it is the one that tells you whether the
remaining minutes mean anything. Ticks and the clock reset when you jump to a
different system; after an EDMC restart the clock starts again at the next
tick.

### Systems you were already in

The route does not depend on catching a jump live. On start-up the plugin reads
the newest journal backwards for the last `FSDJump`, `Location` or
`CarrierJump` and takes the system name, id64 and coordinates from there. That
covers the normal case of launching EDMC while already parked somewhere.

If that system has no bodies stored — scanned before the plugin existed, or
while it was not running — the recent journals are replayed once and the route
is built from that. Both paths are logged:

```
current system read from journal: Synuefe TH-J b42-4
route | no bodies stored for Synuefe TH-J b42-4, replaying recent journals
route | Synuefe TH-J b42-4: 17 stops, 55821 LS, about 114 min
```

### What counts as needing a visit

"Work it" means different things on different runs, so it is a set of ticks in
the preferences. Any one of them is enough to put a body on the route:

| Option | Meaning |
|---|---|
| every body | always fly the lot |
| not discovered by anyone yet | `WasDiscovered: false` - the actual prize |
| not surface-scanned by anyone yet | `WasMapped: false` |
| has bio or geo signals | anything the FSS flagged |
| landable | you can set down on it |
| high value | ELW, water world, ammonia, terraformable |
| has rings | |
| DSS or bio still open | what our own records say is unfinished |

On a 46-body system the difference is the whole trip:

```
every body   32 stops   97390 LS   182 min
landable     17 stops   86264 LS   119 min
high value    1 stop         8 LS     5 min
still open    1 stop         8 LS     5 min
```

Your two criteria for "valuable" — no external database entry, and never
surface-scanned — are the first two ticks. They come straight from the
journal's own `WasDiscovered` and `WasMapped` flags, which the game sets
against Frontier's records, so they are authoritative in a way an EDSM lookup
can never be.

### About the minutes

The estimate is now two separate things, because they behave differently:

* **Travel** — `entry + k * sqrt(distance)`, since supercruise is dominated by
  acceleration rather than cruise speed.
* **On station** — what you do once you arrive. A detailed surface scan and a
  biological sample take very different times, and both are measured.

Both are calibrated from your own journals, and the panel says how many
measurements back them.

**Measuring travel honestly is hard; measuring work is not.** Of eleven
`SupercruiseEntry` → `SupercruiseExit` pairs in the test journals, exactly one
had nothing else happening inside it — the rest contain scans, approaches and
mapping, which is why the same 2961 LS shows up as both 37 and 393 seconds.
Work intervals have no such problem: a sample is bracketed by its own `Log` and
`Analyse` events, and mapping by consecutive `SAAScanComplete` events in one
system, which covers the transfer plus the probe run and is exactly the
per-body rate the estimate needs.

Measured on the test journals:

```
work model from 195 DSS and 12 bio measurements:
  dss 194 s, bio 193 s, approach 45 s
```

Both land near three minutes, which matches the feel of it. The defaults were
150 and 205 seconds, so the calibration moved them by a sensible amount rather
than wildly — a good sign that the brackets are measuring what they claim to.

Timings are filtered with a **trimmed median**, not a mean: journal intervals
are contaminated in one direction only, since the commander can walk away mid-
scan but cannot finish faster than the game allows. The upper tail is noise,
the lower tail is real.

The route summary splits the two so the balance is visible:

```
Synuefe AH-X b20-0: 32 stops in 16 planetary systems, 97390 LS,
about 182 min (178 travel + 4 on station)
```

In a spread-out system almost all of it is transit. The statistics block adds
the other half of the picture — how big the systems around here actually are:

```
systems: 7.5 bodies each on average (2 measured)
```

### Route quality

The optimiser was checked against brute force on every system small enough to
enumerate exhaustively:

| System | Clusters | 2-opt | Optimal | Gap |
|---|---|---|---|---|
| Synuefe TH-J b42-5 | 6 | 2010 s | 2010 s | 0.0% |
| Synuefe VC-J b42-3 | 6 | 2859 s | 2859 s | 0.0% |
| Synuefe TH-J b42-1 | 6 | 1721 s | 1721 s | 0.0% |
| Synuefe TH-J b42-2 | 8 | 3185 s | 3185 s | 0.0% |

Exactly optimal in each case, in under a millisecond. Clustering moons with
their planet is what makes this work: it collapses a 46-body tour into 16
decisions, which is small enough that 2-opt reliably finds the best answer.
There is no gain to be had from a smarter solver here.

## 11. Interface

EDMC's window is shared with every other plugin, so the main panel shows only
what you act on between jumps:

```
Fly     Synuefe QM-N a6-0        7.3 ly
        NEW known, not yet visited
Probe   Synuefe SH-N a6-2   5.0 ly  +-9   [2 in boxel]  odds fair
Here    Synuefe SH-N a6-0   FSS 11/11 | DSS 1 | Bio 1
[Start] [50 v] [copy] [route] [info] [probe]
```

Everything else opens in its own window. A fuel **warning** always appears in
the panel; the full fuel line and the queue counters are off by default and
switchable in the preferences.

| Button | Opens |
|---|---|
| **copy** | puts the flight target on the clipboard |
| **route** | the in-system route with map and checklist |
| **info** | statistics, fuel, all-time totals |
| **probe** | the galaxy map checking controls |

### The probe window

```
check this name in the galaxy map:
    Synuefe DZ-S a42-0
prefix       Synuefe DZ-S a42-
distance     4.2 ly   uncertainty +-9 ly
this boxel   1 candidate   odds void   known to -
queue        973 probes (gap 0, probe 2, empty 971)

[copy prefix] [copy bundle] [not there]  list ends at [  ] [list end] [later]
[replan] [copy FC] [carrier spot] [x] carrier start
```

Clicking **Fly** or **Probe** in the main panel copies that name.
**copy bundle** copies one prefix for several of the next probe boxels when
they share sector, letters and mass code - `Synuefe VA-I b` lists b2, b3 and
b17 (and the other b boxels of VA-I) in one galaxy-map search.

## 12. Orders of magnitude

Measured on a live survey (sector `Synuefe`, mass codes a–d):

| Radius | Boxels total | Without a known system | Flight targets | Probes |
|---|---|---|---|---|
| 50 ly | 984 | 620 | 111 | 842 |
| 100 ly | 6 154 | 5 038 | ~190 | ~5 300 |
| 150 ly | 19 142 | 13 380 | ~190 | ~13 600 |

At 100 and 150 ly the empty-probe list is not workable by hand. Recommended:

* Work the empty probes through the **boxel prefix list** — one search per
  boxel instead of one per candidate.
* For large radii restrict mass codes to `b`–`d`; mass code a boxels are only
  10 ly across and dominate the list.
* Do gaps and probes first — they have by far the highest hit rate.

## 13. Deep space operations

Three things decide how far out you can work, and all three are measured from
the journal rather than assumed.

### Ship fuel

Consumption is strongly non-linear — the drive burns roughly `dist ** 2.7`, so
a 64 ly jump costs hundreds of times what a 6 ly hop does. Averaging the last
few jumps is therefore useless on its own: after a run of short hops it claims
thousands of jumps of range, which is how the first version of this got it
wrong by a factor of 400.

Instead a curve `used = a * dist ** b` is fitted to your own
(`JumpDist`, `FuelUsed`) pairs in log space. On the test journals that gives
**b = 2.75**, which matches the drive's documented fuel power of 2.6 to 2.8 —
strong evidence the fit is measuring the real thing rather than noise.

Range is then quoted for both cases that matter:

```
fuel 171/176t (97%) | 12 jumps at max 64 ly | 7449 at your usual 7 ly
  | burn ~dist^2.8 (15 jumps)
```

Twelve jumps if you range out, effectively unlimited if you keep hopping short.
The panel switches to a warning when it gets tight:

```
FUEL CRITICAL - 1 full-range jumps left, scoop now
fuel low - 4 full-range jumps left, find a KGBFOAM star
```

### Tritium

Tritium is mined from **icy rings**, so an icy ring is what makes a carrier
staging point viable. Ring classes come straight from the `Scan` event and are
stored per body, with the icy ring mass carried through — a bigger ring means a
longer usable seam, which matters if the carrier is going to sit there a while.

The statistics block reports what is available where you are:

```
tritium: 1 system with icy rings here (nearest Synuefe AH-X b20-0 at 0 ly)
```

Measured on the test journals: 29 bodies with rings, 15 of them icy, the
largest at 2.4 × 10¹⁶ MT.

### Where the carrier goes next

**carrier spot** answers the question the `AREA COMPLETE` message raises. It
scores every known tritium system in a volume three spheres wide against three
things that pull against each other:

* overlap with ground already surveyed — wasted effort
* unexplored boxels in the new sphere — the reason to go at all
* tritium on site

Tritium is a **hard gate**, not a weighting: a staging point you cannot refuel
at is not a staging point.

```
next carrier position (tritium on site):
  Synuefe QT-K b41-2    112 ly | 2 icy rings | overlap  3% |
                        847 boxels unexplored | score 3.21
```

It only ever proposes somewhere an icy ring has been seen with our own eyes.
Guessing at unvisited systems would risk sending the carrier somewhere it
cannot refuel — so when nothing qualifies yet it says so plainly:
`no tritium system known far enough out yet - scan icy rings as you go`.

That is also the practical argument for keeping the **has rings** filter on
while working a sphere: every icy ring you scan becomes a candidate for the
next hop.

## 14. Orbital drift, and when the route goes stale

Bodies keep orbiting while the game is paused, while you sit landed, and while
it is shut down. The orbital elements in a `Scan` event are a snapshot taken at
that moment, so every body is now advanced along its orbit by the time elapsed
since - the scan timestamp is stored per body for exactly that.

**How much does it actually matter?** Measured across every body on record:

| Elapsed | Worst drift | Body |
|---|---|---|
| 20 min | 0.53 LS | a moon with a 32 h period |
| 2 h | 3.19 LS | same |
| 12 h | 15.24 LS | same |

Small over a coffee break, real overnight. On a tight cluster where moons sit
2 LS apart, 15 LS is enough to genuinely reorder them.

So rather than rebuild blindly, the plugin **compares and only replaces when
the order actually changed**:

```
route | lift-off: order still optimal (8 LS)
route | game restart: order changed, 11412 LS -> 11208 LS (-204)
```

It triggers on `Liftoff` - which is what ends a surface pause - and on the
synthesised `StartUp` after a game restart, whenever tasks are still open.

## 15. The map

Three sizes via the **size** button (340 / 480 / 640 px), because a dense
system needs the room. The default is now medium rather than small.

The **last body you approached** is drawn as a blue ring with a filled centre
and a `last here` label. The live position is in no journal event, so this is
the closest thing to "you are here" that the data allows - and it is deliberately
a colour that never appears in the theme, so it cannot be confused with a route
marker.

## 16. Statistics window

**stats** now opens its own window, in the host's colours, as labelled tables
rather than a wall of text. Only figures that inform the next decision are
included.

```
Progress in this sphere
  Systems known           146
  Visited                 41  (28.1%)
  Fully surveyed          17  (11.6%)
  Still to fly            109
  Still to check          811

Undiscovered systems
  Certain (boxel gaps)    27
  Estimated further       412
  Estimated total here    ~585
  Boxels closed           7 of 984  (0.7%)
  Boxels never probed     585

What we contributed
  Bodies scanned          164
  Bodies mapped           104
  First discoveries       7

Database coverage
  EDDiscovery             412
  Spansh                  425
  EDSM                    422
  Only one source knows it  11  (9.0%)

This sphere
  Centre                  Synuefe TH-J b42-4  r=50 ly
  Bodies per system       7.5 average over 12 systems
  Time per system         14 min average (9 measured)
  Time in this sphere     2.1 h over 9 systems
  Fuel                    fuel 171/176t (97%) | 12 jumps at max 64 ly

All time
  Systems visited         38
  Distance flown          973 ly
  Bodies scanned          462
  Bodies mapped           231
  First discoveries       13
  First to map            192
  Bio sampled             11
  Boxels closed           14
  Names ruled out         31
  Spheres surveyed        3
```

**Percentages are clamped to 100.** Coverage is measured against an estimate,
and an estimate that turns out low must never produce "112% explored" - that
would destroy confidence in every other number on the page.

Time per system comes from measured intervals between jumps, discarding
anything under 30 seconds or over three hours so that pauses and instant hops
do not distort it.

## 17. What the survey actually pays

Sales are recorded from `MultiSellExplorationData`, `SellExplorationData` and
`SellOrganicData`, and reported in the info window:

```
Earnings
  Exploration data      11.8 M cr from 556 bodies
    per body            21 255 cr
  Biological data      228.7 M cr from 31 samples
    per sample       7 376 423 cr
  Total earned         240.5 M cr over 5 sales
  Bio vs mapping           347x more per unit
```

**That ratio is the most useful number the plugin produces.** Scanning and
mapping 556 bodies earned 11.8 M; thirty-one biological samples earned 228.7 M.
Per unit of effort, bio is over three hundred times ahead - and the bonus is
where it comes from: 164 M of the 228 M was first-discovery bonus, paid only
because nobody had logged those species before.

Two practical consequences:

* Keep **has bio or geo signals** ticked in the visit filters. On the numbers
  above, one sample is worth more than a whole system of mapping.
* First-discovery bonus is the whole game. It is paid for being first, which
  is exactly what the boxel gap hunting is for - a system no database knows
  has never had its organics logged either.

The figures are yours, not estimates: they come from what the game actually
paid at the counter.

## 18. Mining hotspots

Ring scans report their mining materials in `SAASignalsFound`, right next to
the biological ones:

```json
{"BodyName": "Synuefe CC-G b3-0 5 A Ring",
 "Signals": [{"Type": "Rhodplumsite", "Count": 2}, {"Type": "Monazite", "Count": 3},
             {"Type": "Platinum", "Count": 3}, {"Type": "Painite", "Count": 1}]}
```

Those were being discarded - the ingest only looked for Biological and
Geological. Keeping them turns the survey into a mining atlas of your own
making. From the test journals alone:

```
Monazite              7 rings, 17 hotspots
Low Temp. Diamonds    5 rings, 14 hotspots
Rhodplumsite          3 rings, 13 hotspots
Platinum              4 rings,  8 hotspots
Tritium               3 rings,  3 hotspots
```

**mining** opens a searchable list, nearest first:

```
material [Platinum v] [refresh] [close]

system                     ring                        x  ring type  distance
Synuefe ZB-J d10-61        13 A Ring                   3  Icy             12 ly
Synuefe ZB-J d10-61        13 B Ring                   1  Icy             12 ly
Synuefe TH-J b42-2         D 4 A Ring                  1  MetalRich       21 ly
Synuefe CC-G b3-0          5 A Ring                    3  MetalRich      981 ly
```

Clicking a row copies the system name. Choose `(all)` to see everything with
the material named in the last column. The point is the months-later case:
when the carrier needs tritium or you want a platinum run, the answer is
already in your own data rather than a forum search.

## 19. Learning, fuel and commanders

Three later parts are described where they arrived, in the version history:

* **Learning from your own data** (4.7) - counting, averages and 95 % ranges
  from your own prospected rocks, mining runs and Rhino rigs; a thin group
  leans on the broader one (that ring, else rings of its class, else any
  ring), and a value resting on little data is marked as thin. See
  [Learning from your own data](#learning-from-your-own-data); the genus
  forecast from your own samples is in
  [Bio prediction from your own finds](#bio-prediction-from-your-own-finds).
* **Fuel** - the model is in [Deep space operations](#13-deep-space-operations).
  The burn curve is learnt per ship and commander (4.7, [Plugin](#plugin)); on
  a plotted route the briefing names the star to scoop at the latest, with one
  jump in hand (4.8, [Scoop at the latest](#scoop-at-the-latest)).
* **Commanders** - exploration per commander, knowledge shared, a main
  commander for the survey (4.8,
  [Several commanders on one PC](#several-commanders-on-one-pc)); the first
  route after a carrier ride starts at the carrier
  ([First route from the carrier](#first-route-from-the-carrier)).

---

# Version history

Oldest first: the versions at a glance, the fixes of 3.x and 4.0, then
what changed in each release from 4.1 on.

## Version numbers so far

| Version | Notes |
|---|---|
| 4.0.0 | first release: sphere survey, boxel gaps, in-system routing, deep space, mining atlas |
| 4.1.0 | n1 = 0 naming rule fixed, EDDiscovery source working again, bio counter fixed, physical body data stored |
| 4.2.0 | cockpit overlay, bio prediction from own finds, route plot targets through unprobed boxels |
| 4.3.0 | discovery filters fixed, supercruise timing on real legs, atlas for body signals and materials, 30 s briefing |
| 4.4.0 | surface track and finds on bodies, exobiology sample distance in the overlay, SHBOX FIS |
| 4.5.0 | mining block in the overlay, carrier hold from Frontier's Companion API, FIS: galaxy 3D, mining, statistics |
| 4.5.1 | fixes: FIS keeps following a journal the game rewrote, live-link watchdog; mining block only from a prospector in a mining ship |
| 4.6.0 | local first: online sources in shells when needed, daily cap, offline switch, EDDiscovery first; FIS: Rhino rigs and hold, open bio signals, data at risk, on foot, QR code, OBS mode |
| 4.7.0 | Mozilla Public License 2.0; honest information levels in the briefing; fuel model per ship; FIS: known and favourite carriers with docking access, learning from your own mining, themes, combat mode, cockpit configuration, ATLAS SYSTEMS |
| 4.8.0 | exploration per commander with a main commander; first route from the carrier; latest scoop on a plotted route; data lost with the ship planned again; FIS: VEHICLE tab, deeper themes, unsold data with risk level and the first-footfall bonus |
| 4.9.0 | README in a new order; overlay: absolute course, "lost - redo"; route check of a plotted route (one EDSM request); prospecting learnt from your probes; FIS: synthesis per tier and tank size in VEHICLE, docked stations in the SYSTEM map, plot corridor in GALAXY |
| 4.9.1 | fixes: live DSS timing, own carrier after a jump aboard, damaged StarPos, pre-release tags in the update check; journal reading in its own module `journalscan.py` |
| 4.10.0 | sector names computed (EDTS) and hand-authored sectors planned under their own names; codex region in the briefing and the FIS (region map); galaxy map list: catalogue stars fill their number, *list ends at* replaces *boxel done*; probe candidates looked up in EDDiscovery by id64 |

## Fixed since v3.0.8

* **Preferences tab crashed.** `myNotebook.Entry` was removed in EDMC 6.0
  (`AttributeError: module 'myNotebook' has no attribute 'Entry'`, line 1287).
  Now `nb.EntryMenu`, with `tk.Button` for buttons.
* **Preferences tab crashed again in 4.0.0-rc.** Nested `nb.Frame` containers
  used `pack()` inside a grid-managed notebook frame
  (`TclError: cannot use geometry manager pack inside ... managed by grid`).
  The whole tab is now laid out with `grid()` and no nested containers.
* **EDDiscovery hook pointed nowhere.** It looked for `EDDUser.sqlite`; the
  system data lives in `EDDSystem.sqlite`.
* **Wasteful cube tiling.** 27 tiles of 200 ly edge length for a 50 ly radius.
  Replaced by a single sphere query, or a clean 100 ly decomposition.
* **id64 was thrown away.** `survey_state.json` had `id64` null throughout,
  making the exact boxel geometry unusable.
* **Boxel designations were treated as untargetable.** Names like
  `Synuefe XV-C d12` were held back entirely. With exact coordinates behind
  them they are real systems, and their boxels need no probing at all.
* **No durable knowledge store.** `neareststars.json` was rewritten on every
  run and `survey_state.json` was throwaway state.

## Fitting on a 1080p screen

A 29-body system produces a route taller than the monitor. Three changes:

* **The stop list scrolls.** It sits in a canvas with a scrollbar and a mouse
  wheel binding, capped at 360 px. Without it the bottom of a long route -
  including the buttons under it - was simply unreachable.
* **Windows are capped to the screen.** `_fit_to_screen` measures the monitor
  and clamps width and height, leaving a margin. Tk will otherwise place a
  window whose bottom edge is off-screen with no way to get at it.
* **The map got smaller**: 260 / 340 / 460 px instead of 340 / 480 / 640,
  since it now shares the height with a scrolling list. The **size** button
  still cycles it.

### The blank map

The map stopped drawing in large systems. The cause was a one-character class
of bug:

```python
w = int(_route_map.winfo_width()) or _MAP_W
```

Tk reports a width of **1** for a widget it has not laid out yet, and `1` is
truthy - so `w` became 1 instead of the fallback, `span` went negative, and
the function returned without drawing anything. It looked intermittent because
it depended on whether the window happened to be mapped before the first draw.

Fixed by testing the value rather than its truthiness, plus a retry once the
window is mapped:

```python
if w < 40 or h < 40:
    w, h = _MAP_W, _MAP_H
    _route_win.after(150, _route_map_draw)
```

Verified by forcing `winfo_width()` to return 1: the map now draws 3479
elements where it previously drew none.

### The main panel

The statistics block is gone from the panel entirely. It was twelve lines in a
window shared with every other plugin, and every one of those lines is in the
info window already. What remains is four lines and one row of buttons; the
fuel line and queue counters stay off unless switched on, and a fuel **warning**
always shows regardless.

## Ticks are remembered

Working a 30-body system takes longer than one sitting. The ticks are therefore
stored per body in the database, not in a session list - fly out, come back
days later, and they are still there.

```
Synuefe ZB-J d10-61   24 of 29 stops left in 16 planetary systems
10820 LS remaining, roughly 89 min
5 ticked off - kept across restarts
```

Two ways a stop gets ticked:

* **Automatically**, when the journal says you were there - `ApproachBody`,
  `SAAScanComplete`, `Touchdown` and `ScanOrganic` all name the body, so
  normal flying needs no clicking at all.
* **By hand**, for what the journal cannot see: a body you looked at and
  decided to skip.

**reset ticks** clears them for the current system only, and says how many it
removed. The database also tracks which systems are part-worked, which is the
list you want when deciding where to go back to.

## Why the map was a straight line

Early versions projected every system onto the X/Z plane, on the assumption
that orbits sit near the galactic plane. Measured across real systems, that is
wrong most of the time:

| System | spread X | spread Y | spread Z |
|---|---|---|---|
| Synuefe ZB-J d10-61 | 662 | 668 | 615 |
| Synuefe VC-J b42-3 | 1457 | 1276 | **8** |
| Synuefe TH-J b42-1 | 571 | 761 | **3** |
| Synuefe OB-L b41-3 | 1623 | 1280 | **13** |
| Synuefe AH-X b20-0 | 22350 | **10255** | 20161 |

In five of six systems Z is within a few light seconds of zero while X and Y
span thousands - so an X/Z projection collapsed the whole system onto one
horizontal line, which is exactly what it looked like. The one binary in the
set is the other way round, so no fixed plane works either.

The plane is now picked per system by dropping whichever axis varies least.
Every system then spreads across both dimensions:

```
Synuefe AH-X b20-0   plane X/Z   spread u=25332 v=22867  (dropped Y, 11661)
Synuefe ZB-J d10-61  plane X/Y   spread u=  705 v=  662  (dropped Z,   660)
Synuefe VC-J b42-3   plane X/Y   spread u= 1341 v= 1278  (dropped Z,     8)
```

### Labels

Two changes on top of that:

* **Only planets are named.** Moons sit a few light seconds from their planet
  and their labels only piled more text into the same spot.
* **Labels are nudged apart.** They are drawn after all the bodies and each
  one looks for a free slot - right, left, above, below - rather than
  overprinting a neighbour.

On the 29-stop system that takes the map from 29 overlapping labels to 17
readable ones.

## "last here" pointed at the wrong body

`BodyID` is only unique **within a system**. The marker recorded the id but
not which system it came from, so on arriving somewhere new it happily pointed
at whatever body happened to share that number - which is why it stuck to a
plausible-looking but wrong planet.

The system address is now stored alongside, and the marker is drawn only when
the two agree.

## Two fixes

### "last here" stopped moving

The marker was updated only on `ApproachBody`. In a real session that fires 11
times while `Touchdown`, `Liftoff` and `SAAScanComplete` together fire 180 -
so it usually pointed at wherever it had last happened to be set.

Worse, the update sat inside the event dispatch chain, where an earlier
`elif ev in ("ApproachBody", "Touchdown")` branch matched first and swallowed
it. Adding more branches further down could never have worked.

Position tracking now runs **before** the chain, for every event that carries
a `BodyID`, and is cleared on jumping to a different system:

```
FSDJump          -> body=None  (new system, marker cleared)
SupercruiseExit  -> body=4     sys=11673049507177
ApproachBody     -> body=7     sys=84724781754
SAAScanComplete  -> body=16    sys=84724781754
```

### Black on black in the mining dropdown

An `OptionMenu` popup is a separate Tk `Menu` hanging off the button, not a
child in the widget tree - so walking children to apply the theme never
reached it, and it kept Tk's defaults. It is now fetched through the widget's
`menu` option and configured directly, including the highlight colours. The
radius picker in the main panel got the same treatment.

## What changed in 4.1

### Fixes

* **Names without a dash** (`Synuefe XV-C d12`) are now read correctly as
  system n2 of an n1 = 0 boxel - see
  [Names without a dash](#names-without-a-dash-synuefe-xv-c-d12). Candidates
  are generated in the form the game actually uses, and boxel records written
  under the old rule are rebuilt once on start (logged as
  `database repair (n1=0 naming rule)`). Closures backed by a real *not there*
  click are kept.
* **EDDiscovery returned nothing.** Current EDDiscovery stores names packed
  into a `nameid` column and has no SystemAddress column; the plugin took
  `edsmid` for an id64 and every row was dropped. The current layout is now
  decoded directly - tested on a 19 GB `EDDSystem.sqlite`: 723 systems for a
  50 ly sphere in 0.4 s, every name identical to Spansh/EDSM, no position
  differences. A database locked by a running EDDiscovery is reported as
  `busy` instead of raising.
* **Bio samples were counted again on every journal replay** - including the
  automatic one behind the route window. Bodies looked sampled when they were
  not (79 of 91 bodies had more samples than signals on the test data). The
  counter is now the number of distinct species analysed, and the one-time
  replay after the update sets it right.
* **Route window replayed the journals over and over** when arriving in an
  unscanned system. Now once per system and session.
* **Update check** logs why it did or did not run.

### New data per body

Stored from every `Scan` from now on (and from your history by the one-time
replay): radius, mass, surface gravity, temperature, pressure, atmosphere and
its composition, volcanism, material composition, tidal lock, axial tilt,
rotation period, `WasFootfalled`, full ring list with inner and outer radius;
for stars mass, absolute magnitude, age, luminosity class and subclass. Every
`ScanOrganic` analysis records species, genus and variant per body.

Nothing is shown with it yet. It is the groundwork for bio predictions
(which genera are possible on a body before landing) and for features to
come.

## What changed in 4.2

### Fix: options that were on by default were off

EDMC 6 keeps its settings in `config.toml`, and a switch that was never
saved there reads as *off*. The plugin applied its own "on" default only
after asking, so it never took effect: the **update check** has not run since
4.0 for anyone who had not saved the preferences since then, and the new
overlay would have stayed dark. The default now goes to EDMC directly.

### Cockpit overlay

With [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)
installed (or the older EDMCOverlay), two small blocks appear over the game:

```
SHBOX > NEXT TARGETS
1  A 1 d                 1646 LS  BIO 1 Brain Trees
2  B 1                  74714 LS  DSS
3 of 4 left  ~95 min
```

* **NEXT TARGETS** - the next three stops of the in-system route, with the
  distance and what is to be done there; refreshed on every route change and
  every tick. Violet = never discovered, amber = biology still open.
* **BRIEFING** - for thirty seconds after selecting a jump target, and on
  arrival: star class and whether it can be scooped, which databases know the
  system - `IN NO DATABASE - first discovery likely` in violet when none
  does -, open candidates in its boxel, fuel.

The overlay steps aside while the game shows a full-screen view of its own -
galaxy map, system map, orrery, FSS, DSS, codex, station services - and comes
back when you return to the cockpit. Selecting a jump target happens in the
galaxy map, so its briefing is held back and shown the moment you close the
map, instead of covering the map's system panel.

*Preferences -> SHBOXSEARCH -> Cockpit overlay*: on/off, briefing on/off,
position (four corners). The preferences show whether an overlay plugin was
found. Without one nothing happens. The overlay is a separate transparent
window drawn by the overlay plugin - it only displays, nothing is sent to the
game.

### Bio prediction from your own finds

Before a DSS probe the game only says "2 biological signals". 4.2 learns from
every organism you have analysed which conditions each genus was found under
(atmosphere type, planet class, gravity, temperature - the data 4.1 started
storing) and names the likely genera for a body you have not probed yet:

```
Wregoe GI-A c14-6 A 5    SulphurDioxide 0.51 g 282 K  ->  Bacterium?, Stratum?
```

The `?` marks a prediction. After the DSS probe the game names the genera
itself and the plugin shows those instead. Shown in the route list and in the
overlay; the EDMC log states what it learned from
(`bio | bio model from 79 sampled bodies, 12 genera ...`).

How good is it? Measured on the test data by hiding one body at a time and
learning from the rest: the first genus named is right for **89 %** of the
bodies, and 72 % of all genera actually present are among the three named.
No rule table from elsewhere is used - it is your own data, so it improves
with every sample and knows nothing about genera you have never found.

### Route plotting as a probe

Every route plotted in the game writes all its hops - name and exact
position, straight from the game's galaxy - to `NavRoute.json`, which the
plugin harvests. That includes systems no database knows. 4.2 picks a plot
target whose straight line crosses the most unprobed, promising boxels:

```
plot route   Synuefe PG-L b41-4  79 ly, 68 unprobed boxels on the way
             (economical route = more hops = more systems)
```

**copy route target** in the probe window puts the name on the clipboard;
paste it into the galaxy map and plot. Plotting as an *economical* route makes
more, shorter jumps and therefore lands more systems in the database. The
suggestion is recomputed after every jump. You do not have to fly the route -
the plot alone harvests it.

### AI disclosure

The bio prediction compares value ranges and counts from your own samples -
simple statistics, no trained model. Like the rest of the plugin it is not an
AI system under the EU AI Act; see [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md).

## What changed in 4.3

### Fix: "not discovered by anyone yet" never matched

The route filters **not discovered by anyone yet** and **not surface-scanned
by anyone yet**, and the **first** label in the route list, compared the
journal flags with `False`. The database hands them over as `0`, so the test
never succeeded - since 4.0, these filters routed nothing. Measured on the
test data, in the 15 systems that hold undiscovered bodies:

| | before | after |
|---|---|---|
| not discovered by anyone yet | 0 | 207 (all of them) |
| not surface-scanned by anyone yet | 0 | 135 |
| "first" label in the route list | 0 | 207 |

Undiscovered bodies are what the survey is for, so this is the most important
fix since the naming rule in 4.1.

### Fix: supercruise timing measured on the wrong distance

Each supercruise flight was paired with the *arrival distance* of the target
(its distance from the arrival star) - not the distance flown when you hop
from one planet to the next. 4.3 measures body-to-body flights, with the
distance between the two bodies taken from their orbits at the time of the
flight, and also reads them from your existing journals at start-up.

It is deliberately cautious: only flights of 100 LS or more count (shorter
ones are mostly approach and landing), at least 20 are needed, and a fit that
ends on the edge of its range is rejected. Most mapping happens from
supercruise without dropping out, which leaves few clean flights - on the
test data 28, not yet enough - so the defaults stay until enough have been
flown. The EDMC log says which: `supercruise model unchanged: ...` or
`supercruise model from N body-to-body legs: ...`. The live pace correction
in the route window (`actual pace 0.4x the estimate`) is unaffected.

### Atlas: body signals and materials, searchable like ring hotspots

The **mining** button is now **atlas**. Its window has three views, each
searchable, nearest first, a click copies the system name:

* **ring hotspots** - as before.
* **body signals** - everything FSS and DSS report on a body: planetary
  mining locations, geological, biological, thargoid, guardian and human
  signals, the genera the DSS names (**Brain Trees** has its own entry),
  codex sites such as fumaroles and lava spouts.
* **materials picked up** - every `MaterialCollected`, with the body you were
  at (from touchdown / approach; "in space" otherwise). Raw, manufactured and
  encoded, so "where did I get Sensor Fragments" has an answer.

Non-human and Guardian sites on the surface are found with the SRV wave
scanner and leave **no journal event** - only the pickup does. So a body is
also marked as **Non-human site (from pickup)** when Thargoid material
(`unknown...`, `tg_...`, e.g. Sensor Fragment) is collected there, and as a
**Guardian site** for `guardian_...` / `ancient...` material.

The atlas is filled from your history by one automatic journal replay after
the update (logged as `upgrade finished - atlas: N signal kinds, M materials`).

### Smaller fixes

* **Briefing** in the cockpit overlay stays 30 seconds instead of 12.
* **Phantom systems.** Selecting a catalogue system (HIP, HD ...) in the
  galaxy map created a second, procedurally named "system" with the same
  address - one that cannot be found by that name and showed up as a flight
  target. Known addresses are no longer duplicated, the game's own name is
  used for a targeted system, and existing phantoms are removed once
  (`database repair (destination phantoms)`).
* **not discovered by anyone yet** no longer routes to rings as separate
  stops - they are discovered together with their planet.

## What changed in 4.4

### Surface track and finds

On or near a body the game writes latitude, longitude, altitude and heading
to `Status.json`. 4.4 keeps them as a **track per body** - a point every 25 m,
or every 10 s once you have moved a little, split into ship, SRV and on foot.
No journal holds this, so the track only exists from now on and only while
the plugin runs.

Every place where something happened on a body is kept as a **mark**:
touchdown and lift-off, SRV out and in, leaving the ship on foot, each
biological log / sample / analysis with its species, materials picked up,
codex finds, settlements and screenshots. Touchdown, lift-off, codex,
settlement and screenshot carry their own position and are also read back
from your journals (on the test journals: 341 landings, 221 codex finds, 30
settlements on 96 bodies). Samples and pickups have no position in the
journal; they take the last `Status.json` position - only when it belongs to
the same body and the same moment, so replaying an old journal never stamps
today's position on an old sample.

### Exobiology: distance to the last sample

While you sample a species, the cockpit overlay shows the distance to the
previous samples of that species against the minimum distance of its genus:

```
BIO > Bacterium Cerbrus  2/3
580 m / 500 m  OK - sample here
```

The minimum distances are community values (Bacterium 500 m, Osseus 800 m,
Tussock 200 m ...), not published by Frontier - the measured distance is
shown next to them so a wrong value is easy to spot. Brain Trees can be
sampled since the Nomad arrived; their range is 100 m (community value; in
our own samples the game accepted the next sample at 102 m).

### Surface compass in the overlay

On a body - and already in orbital cruise, where `Status.json` reports the
position too - the overlay lists what you may want to get back to, with the
distance and the direction relative to your heading:

```
NAV  bio 2 done, 1 open
NOMAD PARKED                359 m  ^ ahead
Lividum Brain Tree 1/3       46 m  v behind
Gypseeum Brain Tree         903 m  < 13
```

* **the parked SRV** - where you left it on foot, until you get back in
* **the parked ship** - where it touched down, until it lifts off or is sent away.
  The Rhino is dropped by a ship hovering just above the ground, without a
  touchdown; the ship waits at the drop point, shown as *SHIP (hover)* -
  last known, since sending a hovering ship away writes nothing. The Nomad
  gives no such point: the ship flies along at some 2-3 km.
* **species not finished yet**, with the samples taken (a new Log restarts the
  count, as in the game)
* **earlier finds on this body** - codex entries, settlements, screenshots;
  take a screenshot to keep any spot as a waypoint
* genera the detailed surface scan named that you have not started yet

Switch it off under "surface compass" in the settings.

*Rhino mining rigs.* Placing a rig writes nothing to the journal; collecting
it - driving over the folded rig - writes one MiningRefined per tonne. Where
those are written is where the rig stood, so the FIS PLANET view shows the
collected rigs numbered per Rhino launch (*Rig 1 · 11 t Deuterium*). Tonnes
more than 8 s or 25 m apart count as another rig. Journals from before this
version are read once more after the update, so earlier rigs appear too.

*Rhino hold.* Out in the Rhino, PLANET and MINING show its hold (72 t) and how
many full rigs (12 t each) still fit. A rig only goes in whole, so with less
than 12 t free the line turns amber: make room before you collect. Which
rigs are out the game does not say - this is room, not a rig count.

### The Nomad

The flying SRV is launched with `LaunchVessel` and lands with its own
`Touchdown` / `Liftoff`. 4.4 records its launch, tells its landings apart from
the ship's and marks where it is parked. Marks recorded before are repaired
once: leaving the SRV becomes "SRV parked", and landings get their vehicle
from the track.

### SHBOX FIS - flight information system

A companion in your browser, shipped in the `FIS` folder: eight views (briefing,
planet, system, galaxy, planet info, atlas, ship, carrier), English and German,
for a desktop, a 10" tablet or a phone, each view also in a window of its own.
It reads the plugin database and the game's files only. Start it with
`FIS\start_fis.bat` (Python 3.11+); the first start asks a few questions and
remembers them. In EDMC's settings (section SHBOX FIS) you can start it, open it
in the browser, or tick **start the FIS together with EDMC**. Everything else:
[FIS/README.md](FIS/README.md).

### Atlas: tabs and finds on the ground

The atlas window now has one **tab** per kind - **rings**, **signals**,
**materials** and the new **finds**: codex entries, analysed species,
settlements and screenshots, each with the body and the latitude / longitude
where it was, nearest system first. The same thing logged several times on
one body (the codex writes an entry per sighting) is one row with a count.
A screenshot is the simplest way to keep any spot as a waypoint.

Rings in a system known under two names (a catalogue name and a procedural
one) no longer show up twice.

A **distance** picker (25 ly ... 2000 ly, or any distance) keeps the list to
what is around you - far from the bubble, finds thousands of light years back
would otherwise fill it.

### Route: no detours to other stars

Stars other than the one you arrive at are no longer route stops, whatever
the filter: the FSS from the arrival point already discovers them, flying out
to them only made the route longer. On the test systems with "every body"
this saves one stop and 4-5 minutes each; more where a companion star sits
far out.

### Fix: binary moons drawn thousands of LS from their planet

Two moons that circle each other orbit a common barycentre, which orbits the
planet. The journal reports that barycentre (`ScanBaryCentre`) with its orbit
but without saying what it orbits, so the plugin placed it around the
system's origin - in the route map the pair ended up far out in the system.
The parent is now taken from the moons' own `Parents` chain. On the test data
164 barycentres were affected; a pair like "3 d / 3 e" moves from 2141 LS to
4.7 LS from its planet. Existing data is repaired by one automatic journal
replay after the update.

## What changed in 4.5

### Mining in the overlay

While you mine in a ship with mining tools - from the first prospector
limpet (collectors serve other work too); refining alone (ground mining in
the Rhino SRV) starts nothing; gone when you dock, jump, or ten minutes after the last mining
event - the overlay shows five lines:

```
ROCK  Tritium 18.3 % | low | GOOD
HOLD  59 t ore | 141 t free | 122 limpets
RATE  336 t/h | full in ~25 min
SESSION  59 t Tritium | 36 min
LIMPETS  last ~189 t OK
```

In a ring the SESSION line becomes `HOTSPOT  Tritium Hotspot targeted - HUD
compass | 59 t in 36 min`, or an amber reminder when the hotspot is not your
target: then the game's own HUD compass points to the hotspot's centre, which
keeps you oriented in the field. The game reports no position inside a ring
(no latitude, longitude or heading in `Status.json`, no coordinates for a
hotspot), so the plugin cannot draw a map or a compass of its own there.
While the mining block is up, the route targets block steps aside; it returns
ten minutes after the last mining event.

* **ROCK** - the last prospector report: the share of the material you mine
  (the hotspot you target, else what you refine most), its content, and a
  verdict against the best rock of this session (GOOD / FAIR / MOVE ON);
  a motherlode is named
* **HOLD** - ore and limpets on board, free space
* **RATE** - tonnes refined in the last ten minutes, per hour, and when the
  hold is full at that pace (the game writes nothing about the refinery's
  bins, only each finished tonne)
* **LIMPETS** - how many tonnes your limpets last at the rate this session
  uses them; amber when that is less than the room left (every limpet
  launched leaves the hold, so its tonne is free for ore again)

Switch it off under "mining" in the settings.

### Your carrier from Frontier's data

With EDMC logged in to Frontier, the plugin keeps the Companion API's answer
for your fleet carrier in `capi_fleetcarrier.json` (see [Data integrity](#8-data-integrity)). SHBOX FIS
reads the goods in the hold from it - above all the tritium, so the carrier's
range counts the hold too - and the upkeep per week as Frontier bills it.

### SHBOX FIS

Galaxy in 2D and 3D with a replay of your flight path and your carrier,
MINING and STATISTICS views, the carrier in the system map with its ring
hotspots and a system report, jumponium readiness, a hazard log, life
support on foot, a big surface compass, known points on approach, the
search-and-rescue role for the air wing and a settings page. Details:
[FIS/README.md](FIS/README.md).

### 4.5.1 - fixes

* **SHBOX FIS stayed silent after a lost connection.** The game had written
  its journal anew under the same name; the FIS read on past the new end. It
  now reads such a file from its start, a watchdog restarts a stopped reader,
  and a page whose connection went silent reconnects by itself.
* **Mining block only when you mine with a mining ship.** It starts with the
  first prospector limpet in a ship with mining tools; collector limpets (they
  serve other work too), refining in the Rhino SRV and the refinery's last
  tonnes after docking start nothing. A jump ends it, like docking.
* FIS CARRIER: hovering a role column explains how its dots are earned; a
  commander without a carrier of their own sees the ships without a hint that
  assumes one.

## What changed in 4.6

### Local first - fair use of EDSM and Spansh

Both are community services under heavy load. 4.6 asks them as little as
the survey allows (details in "External sources", *Fair use*):

* **In shells, when needed.** The sphere is fetched in 25 ly shells, nearest
  first, and the next shell only when the plan reaches it - after a jump
  close to the edge of what is known, or when nothing is left to do inside.
  A restart of EDMC asks nothing.
* **Remembered, spread out.** Each shell a source delivered stays valid for
  a random 5 to 14 days, so many installations do not ask at the same time.
  *reload online data* asks again on purpose.
* **EDDiscovery first.** Its system database is a copy of Spansh's dump;
  when it was updated within two days, Spansh is not asked at all and the
  local file is read shell by shell. A locked file (EDDiscovery running) is
  read again later. Catalogue names (`HIP 12345`) are now read from it too.
* **One polite gateway** for every request, the update check included:
  pacing per service, the services' own rate-limit headers, back-off and a
  rest for the session after repeated errors, an honest User-Agent, at most
  50 requests per service and UTC day, at most 20 Spansh pages per shell.
  The statistics show *external today: EDSM n of 50 · Spansh n of 50*.
* **offline** in the settings sends nothing at all.
* **Backups.** The database is copied before a schema change or a repair.
* **copy bundle** copies one galaxy-map prefix for several of the next probe
  boxels of one sector, letter group and mass code.
* The FIS brings its own Three.js - the 3D views work without the internet.

### SHBOX FIS

* **Rhino** - the PLANET view numbers the mining rigs where you collected
  them (*Rig 2 · 11 t Deuterium*), shows the Rhino's hold and how many full
  rigs still fit, and the ship hovering at the drop point (the Rhino leaves
  a ship that hovers; no touchdown). Ground mining is a MINING session of
  its own, and the carrier's air wing counts Rhino and exobiology hangars.
* **Biology** - ATLAS BIOLOGY lists the open and the finished bio signals;
  the SYSTEM view folds finished species; the surface map highlights the
  species you are working on.
* **SHIP** - unsold data at risk (exobiology valued, exploration counted)
  and the selected target (destination, FSD target, locked ship).
* **On foot** - suit, mods, weapons and backpack in PLANET.
* **PLANET INFO** - science report under the datasheet, ring hotspots under
  each ring, no more reload on every scan.
* **CARRIER** - the air wing sorts by any column and filters the ship list.
* **Settings page** - a QR code of the home-network address for the tablet,
  display links and an OBS mode, a new access token at a click, and a brake
  for home-network devices (rate and wrong tokens).
* Screenshots from demo data in [FIS/README.md](FIS/README.md).

### Fixes

* The NEXT TARGETS block in the overlay vanished after 15 minutes without a
  route change (a long supercruise leg, on foot, in the SRV); it is now sent
  again in time.
* The route pace said "0.0x, 0 min left" after an EDMC restart halfway
  through a system; only stops ticked since the restart are compared now.

After the update the plugin replays your journals once (Rhino rigs from
earlier outings). Close the FIS window once so it starts with the new files.

## What changed in 4.7

### Licence: Mozilla Public License 2.0

From 4.7 on SHBOXSEARCH and SHBOX FIS are under the **Mozilla Public
License 2.0** (file `LICENSE`). Use, change and share it freely; whoever
passes on a changed file of this project keeps that file open under the same
licence - files of your own next to it stay yours. Every source file carries
the MPL header with an SPDX identifier; the "Incompatible With Secondary
Licenses" notice is not used, so the code stays GPL-compatible for EDMC.
4.6 and earlier were released under MIT and stay MIT. Three.js and the QR
code generator keep their MIT licence.

### Honest information levels

The briefing (overlay and FIS) used to say *in no database - first discovery
likely* for every system the plugin had no source for - also far outside the
survey, where nobody was ever asked. Now it tells apart:

* **known** - EDDiscovery, Spansh or EDSM report it;
* **inhabited** - population, factions or a station seen in your journal:
  every database knows it, no request needed;
* **in no database** - only where a source really delivered that region
  (a fetched shell, still valid) and none of them has it, with *checked:
  EDSM, Spansh*;
* **not checked** - outside our data frame: nobody was asked.

The same rule decides "only known to us" in ATLAS SYSTEMS, GALAXY and the
sphere tile. No new online request.

### Carriers

* **Known carriers** (CARRIER) - also without a carrier of your own: every
  carrier you docked at, started a mission or community goal from, rode
  along with or saw in the FSS, with its last known system and how old that
  is, what you started there and its market when you last opened it.
* **Favourites** - mark carriers with ☆ and a note (also from the tablet);
  they come first, get a ★ in SYSTEM and on the GALAXY map (2D and 3D).
  *online* at a favourite asks Spansh once - on your click, at most every
  six hours, through the plugin's gateway and daily cap, never while
  *offline* is on.
* **BRIEFING: carriers at the target** - your own carrier and your
  favourites whose newest known position is the jump target (without a
  target: the current system), with source and age.
* **Docking access** - SYSTEM's points of interest (one line per carrier,
  with name and callsign) show whether you may dock
  at a carrier (from its market, your own docking requests or the Spansh
  answer): *dockable*, *friends/squadron only*; carriers that refuse you are
  left out.
* **KNOWN CARRIERS tab** - with a carrier of your own the known carriers get
  a tab of their own in CARRIER: docking access, the services found when you
  docked, the last market to unfold with its date, the system to copy, and
  *open system* where the database knows its bodies.
* **Docked at someone else's carrier** - CARRIER shows what its market buys
  (what you carry first, tritium next) and sells.
* Fixes: docking at, or riding along on, someone else's carrier no longer
  moves "your" carrier (plugin and FIS); loading the game on a carrier's pad
  counts as docked.

### Learning from your own data

Counting, averages and ranges from your own journals and the plugin
database - no AI, nothing sent anywhere. What rings and planets yield is
shared knowledge of every commander on this PC; the exploration stays per
commander.

* **PLANET INFO** under each ring: what your prospected rocks held there
  (with a 95 % range), what rocks of rings of the same class held at such a
  hotspot (a thin group leans on the broader one), your tonnes per hour in
  that ring, and what to expect at its hotspots. GROUND MINING: what your
  Rhino rigs yielded here and on bodies of the same class, tonnes per rig
  and rigs per hour.
* **MINING: best hotspots for you** - the nearby hotspots ranked by your own
  tonnes per hour there (that ring, else rings of its class, else any ring).
* **STATISTICS: learning status** - how many rocks, runs, rigs and analysed
  bodies each part rests on, and where it is still thin.

### SHBOX FIS

* **Themes** - standard, Federation console, Belt industrial, Station era and
  Next with an accent colour of your own, per browser (footer).
* **Combat mode** - hardpoints out: *READY · ANALYSIS* in the analysis HUD,
  *COMBAT MODE* in the combat HUD, with shields, hull and interdictions.
* **Cockpit configuration** (settings): views for extra screens, opened and
  closed with one click; the FIS can be installed as an app on the game PC.
* **ATLAS SYSTEMS** - the survey sphere by state (not visited, visited,
  surveyed, known to no online source, checked and not existing), export as
  CSV or JSON.
* **SYSTEM** - points of interest from your own journals (stations,
  settlements, fleet carriers, nav beacons); *nav beacon scanned - all bodies
  known*; *back to the current system* from a pinned one.
* **PLANET INFO** opens on the body of your last fix and follows it.
* **GALAXY** - *copy name* for the game's galaxy map.
* **SHIP: unsold data** counts the bodies you scanned or mapped since you
  last sold that system - honking a system you sold before is no new data.
* **Tablets** - pages and modules are kept by the browser and only checked
  for changes, so a reload no longer fetches Three.js again; the 3D views
  load at the first try.

### Plugin

* **Route** - the arrival star as first stop is optional ("start the route
  at the arrival star"); the pace is taken leg by leg as a median, so a
  repair stop or side work no longer decides it.
* **System map** in the route window pulls apart bodies that land on one
  spot.
* **Fuel** - the burn curve is learnt per ship and commander (another
  ship's jumps made a long-range explorer look short of fuel); no "fuel low"
  in the briefing when the jump target is a scoopable star.
* The panel names the **open bio signals**; partly done bodies count.
* A **commander switch** drops the previous commander's system and route.
* **Nav beacons** - the body data a beacon hands over is stored, but it is
  not your scan (no discovery, no exploration data): mapping and bio are
  still planned.
* No shell is fetched while the commander is far outside the sphere.
* Code scanning findings fixed (static files, sanitising), the self-test
  workflow reads the repository only.

After the update close the FIS window once so it starts with the new files.

## What changed in 4.8

### Several commanders on one PC

Two commanders sharing one PC used to share one "visited / scanned / mapped"
record, so the second commander's route skipped bodies the first had mapped.
Now each commander (by their Frontier ID) keeps their **own exploration** -
visited, FSS complete, bodies scanned and mapped, first discoveries as their
own scan saw them, species analysed - while the **knowledge stays shared**:
body classes, orbits, signals, rings, hotspots, finds and the bio model.

* **Main commander** - a setting in the plugin and in the FIS settings;
  *automatic* picks the commander with a fleet carrier of their own, else the
  one with the most sessions. The survey sphere, its work queue, the
  statistics and GALAXY count for that commander.
* The **in-system route**, the panel line and the briefing show what the
  commander playing still has to do; *also explored by ...* where another
  commander of this PC has been.
* The database gets schema 5. On the first start the plugin makes a backup
  next to the database and replays the journals once in the background
  (about 15-20 s) to sort the history by commander.

### First route from the carrier

Riding along on a fleet carrier you start at the carrier, not at the main
star. Arriving by carrier jump - or loading the game docked at a carrier -
in a system you have not explored yet, the route of this visit starts at
the carrier's body (its position on its orbit, the arrival star left out).
Every other arrival starts at the main star as before. Plugin and FIS.

### Scoop at the latest

On a plotted route of two or more jumps the briefing (overlay and FIS
NAVPOINTS) says at which star you must scoop **at the latest** - from your
tank, your own fuel curve for this ship and the scoopable stars (KGBFOAM) on
the route, with one jump in hand. Stretches without a scoopable star that
need more than a full tank are named; *fuel runs low / out by jump n* when
no star on the way is left.

### Data lost with the ship

When the ship is destroyed, every scan, map and analysed species you had not
sold yet is gone. The plugin now undoes them for that commander - the route
plans those bodies again, the bio counts as open - and marks them lost
until you redo them. FIS SYSTEM says *data lost in the crash: n bodies to
redo*; SHIP lists the systems (with a copy button for the galaxy map); with
more than ten they move to a **LOST DATA** tab, where you can hide systems,
single items or everything farther than 100 / 250 / 500 / 1000 ly from the
list (asked twice; the tasks stay planned).

### SHBOX FIS

* **VEHICLE tab** - the SRV (Scarab, Rhino) or Nomad out now, or the last
  trip: the edition it was bought in, state (driving, flying, landed, you on
  foot), its own tank and what it used, cargo and refined tonnes per
  material, position and heading with an arrow and the distance to where you
  left the ship, the switches (lights, drive assist, turret ...), bio scans
  and landings. Hull, ammunition and modules of a vehicle are in no game
  file. Fix: in the SRV the ship's tank no longer shows 0 t.
* **Themes** change shapes, not only colours: *Federation console* rounded
  panels and pill bars, *Belt industrial* notched plates with rivets and
  hazard stripes, *Station era* phosphor glow, a fine grid and tube-dark
  edges. Same layout and sizes.
* **Unsold data** - a risk level: low below 50 M Cr, moderate from 50 M,
  high from 100 M; systems you discovered first and species on bodies of
  your first footfall are named apart and make it at least moderate. The
  first-discovery bonus (x5) is counted only on a body of your first
  footfall - checked against real sales; "first logged" alone pays the base
  value.

## What changed in 4.9

### This README in a new order

Operation first - what you need, install, update, files, first start,
preferences, known limits -, then the third-party parts, then how it works
with the maths, the version history oldest first and the part for
maintainers. Nothing was dropped; the chapters of "How it works" are
numbered anew. The FIS README follows the same order.

### Overlay: course and losses

* Every point in NAV / KNOWN POINTS names its **absolute course** next to
  the turn - *brg 255 < 30* - to compare with the game's own compass.
* A species **lost in a crash** no longer counts as done: the head says
  *n lost - redo*, and a line points to where it was sampled until it is
  analysed again.
* The head line keeps to the block's width; the genera the DSS named and
  nobody found yet are listed as *to find:*.

### Synthesis and tank in the VEHICLE tab

* **SYNTHESIS** - refuel, ammunition and repair by tier, learnt only from
  your own synthesis: what each needs and what is on board, how often it can
  still be made and what limits it; a tier not made yet is named as such.
  Anything else made while a vehicle is out (the Rhino's rig) is learnt the
  same way under its own name. Nothing is copied from a wiki.
* **Tank size** - no game file names it. Right after a refuel synthesis the
  tank is full, so that reading is kept as the size of the vehicle type
  (`FIS/vehicle_tanks.json`) and the tank shows its fill against it.

### Places in the SYSTEM map

Stations you docked at stand beside their body in the map. The game names
no parent body for a station, so it is matched on its distance from the
arrival star against the scanned bodies; without a match it stays in the
list. Your own carrier is always drawn where the game says it parks; your
favourite carriers stay in the map as long as their newest known position -
your journal or the Spansh lookup - is this system (beside their body, else
beside the main star); other carriers for a day after docking.

### Finding unknown systems

* **Route check** - a plotted route of two jumps or more through space no
  source was asked about is checked once: EDDiscovery's file first, then
  the rest with ONE EDSM request by name. The briefing then says *known* or
  *in no database (checked: EDSM)* there instead of *not checked*; the same
  route plotted again asks nothing (see *Fair use*).
* **Prospecting learnt from your probes** - the statistics window shows how
  often boxels of each score band really held a system. From five such
  finds on, the probe order follows what actually paid.
* **Corridor in GALAXY** - the plugin's plot suggestion (where a route
  crosses the most boxels never probed) as a layer of its own, 2D and 3D.
  Plotting stays yours.

After the update close the FIS window once so it starts with the new files,
and keep `FIS/vehicle_tanks.json` like `favourites.json`.

### 4.9.1 - fixes

* **Live DSS timing never measured anything.** A second branch for
  `ApproachBody` in the journal handling came after one that already took
  the event, so the arrival at a body was never stored and the work model
  learnt mapping times only from the journal replay at start. Live and
  replay now share one meter, so a session measures the same way the
  replay does (arrival at a supercruise exit included).
* **Own carrier stayed in the old system after a jump aboard.** The panel
  showed the new system only after the next carrier location; the database
  was right. It now follows the jump at once.
* **A damaged position no longer breaks the next survey start.** A
  `StarPos` that is not three numbers is ignored instead of being stored
  as the position. The game always writes three numbers; this guards
  against damaged lines and other tools.
* **Update check:** a pre-release tag such as `5.0.0-beta1` no longer
  looks newer than `5.0.0`.
* FIS: a request that is too large is read before it is refused, so the
  answer arrives instead of a reset connection.
* Inside: the journal file reading moved from `load.py` to the new
  `journalscan.py`, and the plugin's journal handling has tests of its
  own. **Copy `journalscan.py` together with `load.py`** when you update
  by hand - without it the plugin does not start. Nothing new is stored;
  no replay is needed.

## What changed in 4.10

4.10 is about one thing: fewer galaxy map searches for every system no
database knows. Measured in the developer's sphere (r = 50 ly): the probe
queue went from 1 902 to 856 candidates, and the "certain" gaps from 959 to
5 - the other 954 were systems EDDiscovery knew all along.

### Sector names computed, named sectors planned under their names

* The name of a sector comes from its place in the grid, computed with
  EDTS's algorithm (Andy Martin, BSD 3-Clause, in `edts_pgnames/`). Boxels
  in a sector where no system is known yet are planned too. Checked against
  EDDiscovery: 399 013 procedural systems all correct.
* About 470 hand-authored sectors (*NGC 2232*, *Col 70*, *Col 285* ...) lie
  over the grid. Inside them the planner probes under the sector's own
  name; before, a test sphere in NGC 2232 Sector gave 540 probes the galaxy
  map can never find and not one gap. A boxel cut by a sphere's surface
  carries both labels; its numbers are counted across them, and the probe
  window says `edge  also named: ...`. See
  [Named sectors over the grid](#named-sectors-over-the-grid).

### Codex region

Ben Peddell's region map (MIT, in `regionmap/`) names the codex region of a
position: a `REGION` line in the cockpit briefing, a REGION row in FIS
BRIEFING (with *new region - you leave ...* when the jump leaves yours) and
the region in the GALAXY focus. Local, no network; 41 of 41 codex entries
from the developer's journals match.

### The galaxy map list

* **Catalogue stars hold a number.** `Synuefe RH-U c19-` lists 1 to 21 and
  no `-0`: slot 0 is HIP 33254. The plugin counts a boxel's numbers by id64
  as well as by name, so a missing number below the highest one is neither
  a gap nor the end. See
  [Catalogue stars hold a number too](#catalogue-stars-hold-a-number-too-since-410).
* **list ends at [n]** replaces **boxel done**: type the highest number the
  list shows (the field starts with the highest one known) and press
  **list end** or Enter. Probes above it go; numbers above what was known
  become certain gaps; a smaller number than a known one is refused.
* **not there** below the highest known number only rules out that name.
  Before, it closed the boxel there and dropped every candidate.
* A name known meanwhile - a target picked in the list, a plotted route -
  leaves the probe queue wherever it stands.

### Candidates looked up in EDDiscovery by id64

A boxel reaches beyond the sphere, and EDDiscovery was read only to its
radius. Every plan now looks its candidates up in EDDiscovery's file by
id64 - local, read only, by primary key, no network - and walks each boxel
upwards until EDDiscovery has no number. A row counts only where its
position lies in the boxel its number names. See
[Candidates looked up in EDDiscovery by id64](#candidates-looked-up-in-eddiscovery-by-id64-since-410).

### Updating to 4.10

* Copy the two **new folders** `edts_pgnames` and `regionmap` with the
  `.py` files - without `edts_pgnames` sector names fall back to what the
  plugin has seen.
* The first start makes a backup of the database and runs one repair: a
  boxel closed at or below a system that exists in it is opened again (in
  the developer's database: none). A running sphere then reads
  EDDiscovery's file once more (the rows read before carry no id64).
* No new column, no journal replay. Close the FIS window once so it starts
  with the new files.

---

# For maintainers

## Releasing (for whoever maintains this)

The update check compares the running `VERSION` against the newest release
tag, so the two have to be set together or the notice lies.

### Checklist

1. **Bump `VERSION` in `load.py`.** It is the single source of truth:

   ```python
   VERSION = "4.1.0"
   ```

2. **Decide the number by what changed**, since the notice is the only thing
   the user reads before updating:

   | Change | Bump | Note in the release |
   |---|---|---|
   | fix, no new data stored | patch, `4.0.1` | — |
   | new feature, new database column | minor, `4.1.0` | **say to run *Replay journals*** |
   | database rebuilt, settings reset | major, `5.0.0` | say what is lost |

   The migration adds columns by itself, but it cannot fill them from history -
   only the commander can decide to replay. If an update adds per-body data
   and the note omits that, the new fields silently stay empty.

3. **Run the self test** - `python procgen.py` must print `failures: 0`.

4. **Commit, tag and push.** The tag has to match `VERSION`; a leading `v` is
   optional because the comparison strips it (4.0.0 was tagged `4.0.0`). Stick
   to one style - `v4.1.0` from now on:

   ```
   git add -A
   git commit -m "4.1.0: <what changed>"
   git tag -a v4.1.0 -m "4.1.0"
   git push && git push --tags
   ```

5. **Create the release on GitHub** from that tag. The description becomes the
   `body` the plugin writes into the log, so write it for a reader deciding
   whether to bother - the first eight lines are what get logged.

6. **AI disclosure.** End the release notes with the footer from
   [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md), section 4, and end every commit
   the AI assistant took part in with the `Co-Authored-By: Claude …` trailer.
   If a release adds an AI feature that runs inside the plugin, update
   `AI_TRANSPARENCY.md` and `ai-disclosure.json` first (section 3 there says
   what changes).

### How the check behaves

* Once per start, and at most once per 24 hours; the timestamp is remembered.
* `Preferences -> Check for update` forces one, and reports `up to date` when
  there is nothing new.
* Every failure is swallowed, and every way out of the check - switched off,
  checked less than 24 h ago, rate limited, no network - is logged at INFO
  (from 4.1; 4.0 left no trace at all). Rate limiting (GitHub
  allows 60 unauthenticated calls per hour per address), no network, no
  release published yet - none of it produces an error the user sees. An
  update check must never be the reason something appears broken.
* Version comparison is numeric per component, so `v4.10.0` correctly beats
  `v4.9.0`. Anything unparseable sorts lowest and therefore never triggers a
  false notice.
* Switchable off in the preferences.

After a release, add its row to
[Version numbers so far](#version-numbers-so-far).
