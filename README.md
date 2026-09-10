# SHBOXSEARCH v4.0

Systematic, exhaustive sphere survey for Elite Dangerous. EDMC plugin.

Goal: completely explore a chosen radius (50 / 100 / 150 ly) around a start
point — find every system, fly there, scan it and map it, with particular
weight on systems that appear in no public database.

Tested against EDMC 6.1.2 / Python 3.13.

---

## 1. Why this is necessary

EDSM, Spansh, EDAstro, EDDB, Inara and the EDDiscovery database are all
**aggregators of EDDN uploads**. They only know what players have uploaded.
Frontier operates no public galaxy API, and the Stellar Forge has not been
reimplemented.

That makes the **game client the only authority on which systems exist**. A
genuinely complete sphere survey has to ask it.

SHBOXSEARCH does exactly that: it derives from the procedural naming rules
which systems *must* exist, and lets the client confirm them.

---

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
id64 yields the full name back.

---

## 3. The gap logic

Within a boxel, `n2` runs **contiguously from 0** (true for mass codes a–g;
mass code h has culling gaps, which is why h is off by default).

Three kinds of candidate follow from that:

| Kind | Meaning |
|---|---|
| **gap** | `n2` missing between 0 and the known maximum → almost certainly exists, but is in no database |
| **probe** | `n2` above the known maximum → finds the end of the boxel |
| **empty** | boxel with no known system at all → one lookup on `-0` decides whether it holds any stars |

---

## 4. Existence checks without guesswork

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
| **boxel done** | you have seen the full list → closes the boxel, drops **all** its remaining candidates at once |
| **not there** | a single name is missing → closes the boxel from that number up, because n2 is contiguous |
| **later** | move this boxel to the back |

Any system you click in that result list sets it as target, which fires
`FSDTarget` and writes `Destination` — the plugin picks both up on its own, so
new finds land in the database without you typing anything.

The probe queue is grouped **per boxel**, not by raw distance, so you work one
search at a time instead of hopping between boxels:

```
Synuefe SH-N a6-2   Synuefe SH-N a6    5.0 ly
Synuefe SH-N a6-3   Synuefe SH-N a6    5.0 ly
Synuefe OB-P a5-2   Synuefe OB-P a5    5.9 ly
Synuefe OB-P a5-3   Synuefe OB-P a5    5.9 ly
```

The probe line shows how many candidates the current boxel still has, so you
know what a single **boxel done** is worth.

**What this changes in practice.** At r=50 ly a sphere holds roughly 800 open
candidates spread over about 600 boxels. Candidate by candidate that is 800
searches. Prefix plus **boxel done** turns it into about 600 — and every boxel
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

## 5. Automatic harvesting

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

---

## 6. External sources

| Source | Priority | Notes |
|---|---|---|
| **EDDiscovery** (`EDDSystem.sqlite`) | 10 | local, no rate limit, very complete. The table and the coordinate transform are detected at runtime: candidate transforms are first tested against a sample of rows for plausibility, then verified against the system you are currently in (id64 plus exact position from the journal). The status line reports `verified` or `unverified`. |
| **Spansh** | 20 | `POST /api/systems/search`, paged at 500. Index is rebuilt daily from the galaxy dump → up to 48 h behind. |
| **EDSM** | 30 | `sphere-systems`, 100 ly radius cap. Larger radii are split into 100 ly sub-spheres. Leaky-bucket rate limit; HTTP 429 aborts cleanly. |

Deliberately **not** used:

* **EDDN live stream** — would need `pyzmq`, which EDMC does not ship; hit rate
  in a remote sphere is effectively zero.
* **Spansh galaxy dumps** — hundreds of gigabytes, not viable inside a plugin.
* **`ImportStars.txt`** as a bulk existence oracle — elegant in theory,
  unreliable since Odyssey, and it overwrites the real visited-stars cache.
  Too risky for data integrity.
* **Frontier cAPI** — commander, ship and station data only.

---

## 7. Data integrity

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

---

## 8. The two work queues

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

### Boxel designations without a number

Names of the form `Synuefe XV-C d12` carry no running number. Frontier omits it
when a boxel holds **exactly one** system, so such a name is a real, flyable
system — and the boxel around it is complete: no `-0`, `-1` … exist there.

Two consequences:

* If the entry carries exact coordinates (journal, EDSM, Spansh, EDDiscovery)
  it goes straight into the flight list. Only unverified entries from legacy
  JSON or POI lists are held back in a `check` category.
* Its boxel is marked complete, so no probes are generated for it. On the test
  data that removed **131 pointless galaxy map lookups** at 50 ly.

Verified on the live data: all 34 such names sit in boxels that contain no
numbered systems at all.

---

## 9. In-system routing

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
body.

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

From the first tick the plugin also measures itself. Elapsed time against the
legs already completed gives an honest correction for the rest:

```
actual pace 2.4x the estimate - remaining is more like 409 min
```

That line appears in the window header and in the log. It is the only check the
plugin can make on its own model without guessing, and it is the one that tells
you whether the remaining minutes mean anything. Ticks and the clock reset when
you jump to a different system.

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

### About the minutes

The time model is `entry + k * sqrt(distance)`, because supercruise time is
dominated by acceleration, not cruise speed. It is calibrated against your own
clean `SupercruiseEntry` → `SupercruiseExit` segments, refitted every eight
measurements, and the panel says how many runs back it: `(model from 24 of
your own runs)`.

Be honest about what that number is worth. Measurements taken from real
journals scatter by more than a factor of five for the same distance, because
scanning, mapping and landing time is mixed into the same interval — 2961 LS
appeared once as 193 seconds and once as 1999 seconds. The calibration
therefore fits the **lower envelope**, on the reasoning that noise only ever
inflates a measurement. Treat the minutes as a rough budget, not a promise.

The **order**, though, barely depends on those constants. It depends on the
geometry, and the geometry is accurate to about one percent.

## 9. Interface

```
Fly     Synuefe QM-N a6-0        7.3 ly
        NEW known, not yet visited
Probe   Synuefe SH-N a6-2   5.0 ly  +-9   [2 in this boxel]
Here    Synuefe SH-N a6-0    FSS 11/11 | DSS 1 | Bio 1
[Start] [50 v] [replan] [stats]
[prefix] [not there] [boxel done] [later]
[copy next] [copy FC] [route] [x] carrier start
r=50 ly | fly 109 (new 105, tasks 4) | probes 811 (gap 27, probe 192, empty 592)
ready
```

* Clicking **Fly** or **Probe** copies that name to the clipboard.
* Distances are measured **from your ship**, not from the sphere centre, and
  are re-ranked after every jump. If you drift outside the sphere the queue
  automatically leads you back in by the shortest hop.
* **copy next** puts the flight target on the clipboard, **copy FC** the fleet
  carrier's system - the way home.
* **stats** folds the statistics block in and out.

### Statistics block

```
known 146 | visited 41 | fully surveyed 17
certain unknown 27 | estimated 412 more (sample 34 boxels) | total ~585
coverage 23.7% visited | 9.8% surveyed
boxels 7 closed / 96 open / 585 never probed  (of 984, 1% done)
bodies 164 scanned, 104 mapped | first discoveries 7
open: 109 flight, 811 probes
carrier: Synuefe CC-G b3-0  (V2L-07J)
sphere: Synuefe SH-N a6-0  r=50 ly
```

| Line | Meaning |
|---|---|
| **known** | systems in the database inside the sphere |
| **visited** | of those, actually flown to |
| **fully surveyed** | visited, FSS complete, nothing left to map or sample |
| **certain unknown** | boxel gaps - they exist, no database has them |
| **estimated** | statistical guess for boxels nobody has probed |
| **boxels closed** | end of the boxel proven, nothing left there |
| **boxels open** | systems known, but the upper end not yet found |
| **never probed** | completely unknown, one lookup each decides |

**The estimate is honest about its own basis.** It is computed only from
boxels *you* probed to the end, never from database contents — a boxel appears
in EDSM or Spansh precisely because somebody found a system in it, which makes
it a biased sample that would inflate the number badly. Below 20 probed boxels
the plugin refuses to guess and shows `estimate needs N more probed boxels`
with a lower bound instead.

**AREA COMPLETE** appears once the flight queue and the probe queue are both
empty and no sector is unresolved. That is the signal that the sphere holds
nothing more and you can move on.

### Two ways to start

| Mode | Sphere centre |
|---|---|
| **free start** (checkbox off) | your current system |
| **carrier start** (checkbox on) | the remembered fleet carrier |

Carrier start gives you a fixed anchor: the sphere stays put while you range
around it, replanning always measures from the carrier, and the way home is
one click away. The carrier position is picked up automatically from
`CarrierJump`, `CarrierLocation` and from docking at it.

### Sphere history and overlap

Every sphere you start is recorded. When you start a new one the plugin
computes how much it repeats earlier work, before you fly a single jump:

```
overlap 43% | 13 systems already visited | move 100 ly for none
```

The volume share comes from the exact lens formula for two intersecting
spheres; the system count comes from your own database. Already-visited
systems never enter the flight queue again in any case, so overlap costs you
planning clarity rather than duplicated flying - but the number tells you how
far to move for a genuinely fresh area.

## 10. Preferences

**Survey** — radius (50/100/150), active mass codes, probe depth above the
boxel maximum, empty probes on/off, queue outstanding scans on/off, jump range,
carrier start on/off, statistics block on/off. Shows the remembered carrier and
the last six surveyed spheres.

**Data sources** — EDDiscovery / Spansh / EDSM individually switchable, path to
`EDDSystem.sqlite` with a file picker, per-source status line.

**Automatic harvesting** — read NavRoute, read target selection, auto-copy.

**Maintenance** — run first import, replay journals, import JSON, export plan
as CSV, export boxel prefixes, self test, database statistics.

---

## 11. Orders of magnitude

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

---

## 12. Known limits

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
* The EDDiscovery source supplies coordinates and id64; procgen names are
  rebuilt from those. Catalogue names (HD, HIP …) still come from EDSM/Spansh.

---

## 13. Installation

**No Python installation is required.** EDMC ships its own interpreter and the
migration runs inside the plugin.

1. Copy the six `.py` files into
   `%LOCALAPPDATA%\EDMarketConnector\plugins\SHBOXSEARCH\`, replacing the old
   `load.py`. Leave `neareststars.json` and `survey_state.json` in place — they
   are still needed.
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

`migrate.py` is included only in case you ever have your own Python. It is not
needed for normal operation.

---

## 14. Fixed since v3.0.8

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
