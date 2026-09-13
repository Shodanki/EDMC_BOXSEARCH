# SHBOXSEARCH v4.0

Systematic, exhaustive sphere survey for Elite Dangerous. EDMC plugin.

## Install

1. Download this repository (green **Code** button -> **Download ZIP**, or
   `git clone`).
2. Copy the folder into EDMC's plugin directory and name it `SHBOXSEARCH`:

   | OS | Path |
   |---|---|
   | Windows | `%LOCALAPPDATA%\EDMarketConnector\plugins\SHBOXSEARCH` |
   | macOS | `~/Library/Application Support/EDMarketConnector/plugins/SHBOXSEARCH` |
   | Linux | `$XDG_DATA_HOME/EDMarketConnector/plugins/SHBOXSEARCH` |

   The eight `.py` files must sit directly in that folder, not in a subfolder.
3. Restart EDMC.

On first start the plugin reads your existing journals and builds its database.
That takes a few minutes with a long flight history; EDMC stays usable. Watch
the plugin's status line, or the EDMC log for `first-run import finished`.

No Python installation is needed - EDMC ships its own interpreter. There are no
third-party dependencies.

## Update

1. Close EDMC.
2. Replace the `.py` files with the new ones. **Leave `shboxsearch.sqlite`
   alone** - that is your survey data.
3. Start EDMC.

The database migrates itself: new columns are added in place, nothing is
dropped. After an update that adds new per-body data, run
*Preferences -> SHBOXSEARCH -> Replay journals* once so the new fields are
filled in from your history.


## Files

All eight `.py` files go in the plugin folder. `shboxsearch.sqlite` is created
on first run and is **your data** - never overwrite it on an update.

| File | Lines | What it does | Depends on |
|---|---|---|---|
| `load.py` | 3204 | EDMC entry point: panel, windows, journal handling, all UI | all of the below |
| `sysdb.py` | 1173 | SQLite store: systems, bodies, boxels, hotspots, earnings, spheres | `procgen` |
| `sysroute.py` | 735 | In-system routing: Kepler positions, 2-opt tour, cost model | — |
| `boxelplan.py` | 619 | Sphere planner: gaps, probes, prospecting score, statistics | `procgen`, `sysdb` |
| `sources.py` | 443 | External data: EDDiscovery, Spansh, EDSM | — |
| `procgen.py` | 410 | Name ↔ id64 ↔ boxel maths, sector registry, self test | — |
| `deepspace.py` | 313 | Fuel model, tritium rings, carrier staging | — |
| `migrate.py` | 72 | Optional command-line import (the plugin does this itself) | `sysdb`, `boxelplan` |

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
```

The last two are legacy import sources and personal data - they belong on your
disk, not in the repository.

### Requirements

* EDMC 5.10 or newer (tested against 6.1.2 / Python 3.13)
* Elite Dangerous: Odyssey journals
* Optional: EDDiscovery, for a fast local system database

### Uninstall

Delete the folder. `shboxsearch.sqlite` goes with it, so copy it out first if
you want to keep the survey record.

---

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

## 9. Interface

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
this boxel   1 candidate   odds void
queue        973 probes (gap 0, probe 2, empty 971)

[copy prefix] [not there] [boxel done] [later]
[replan] [copy FC] [carrier spot] [x] carrier start
```

Clicking **Fly** or **Probe** in the main panel copies that name.

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


---

## 15. Deep space operations

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


---

## 16. Orbital drift, and when the route goes stale

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

## 17. The map

Three sizes via the **size** button (340 / 480 / 640 px), because a dense
system needs the room. The default is now medium rather than small.

The **last body you approached** is drawn as a blue ring with a filled centre
and a `last here` label. The live position is in no journal event, so this is
the closest thing to "you are here" that the data allows - and it is deliberately
a colour that never appears in the theme, so it cannot be confused with a route
marker.

## 18. Statistics window

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

## 19. Preferences layout

Two columns instead of one stack, because the full set ran off the bottom of a
1080p window. Left holds everything about the survey itself (sphere, mass
codes, what counts as needing a visit); right holds sources, harvesting and
window behaviour; maintenance buttons run full width in a 3x2 grid underneath.


---

## 20. What the survey actually pays

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


---

## 21. Fitting on a 1080p screen

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


---

## 22. Ticks are remembered

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


---

## 23. Why the map was a straight line

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


---

## 24. Mining hotspots

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

## 25. "last here" pointed at the wrong body

`BodyID` is only unique **within a system**. The marker recorded the id but
not which system it came from, so on arriving somewhere new it happily pointed
at whatever body happened to share that number - which is why it stuck to a
plausible-looking but wrong planet.

The system address is now stored alongside, and the marker is drawn only when
the two agree.

## 26. Gap logic, re-checked

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


---

## 27. Two fixes

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
