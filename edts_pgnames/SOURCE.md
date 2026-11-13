# edts_pgnames - third-party code, derived and modified

* **Project:** EDTS - Elite: Dangerous Tools Scripts, by **Andy Martin**
  (CMDR Esvandiary) - <https://bitbucket.org/Esvandiary/edts>
* **Licence:** BSD 3-Clause, "Copyright (c) 2016, Andy Martin. All rights
  reserved." - full text in [`LICENSE.txt`](LICENSE.txt), unchanged. It must
  stay with these files. The name of the EDTS project is not used to endorse
  this plugin.
* **Credits named by EDTS:** CMDR Jackie Silver, without whose research the
  name algorithm would not exist, and CMDR furrycat.
* **Game data:** the naming scheme, the name fragments and the hand-authored
  sector names are the work of Frontier Developments plc (Elite Dangerous).
  The sector tables were worked out by the community.
* **Revision:** commit `5d65cb65a53c5a814dab0421823243a5522c4c30` (17.12.2025),
  read on 13.11.2026. SHA-256 of the original files:
  * `edtslib/pgdata.py` `55cd8f8885c2ef30dbb7bcd1c9a2bc32590d4eac99d42c98a98664691181b3dc`
  * `edtslib/pgnames.py` `598d1606a7bc06a973956f5fb31937634a904adc5dfa02890246fa92f51bac8a`
  * `edtslib/sector.py` `854b26ebc61a60d8942b609cf5d81097c8177488a2d565eb50e2dd9c7bb0711b`
  * `LICENSE.txt` `a9c9690a5d6da2e1f07fa7b49f6f31c6d8a019ea1194547e4e726a2f83a6cdf1`

## What was taken and how it was changed

| File here | From | Change |
|---|---|---|
| `pgdata.py` | `edtslib/pgdata.py` | only the imports (`_geom` instead of `sector` / `vector3`); every table unchanged |
| `_geom.py` | `edtslib/sector.py`, `edtslib/vector3.py` | reduced to the sphere, the region and its grid origin |
| `pgnames.py` | `edtslib/pgnames.py`, `jenkins32` / `interleave` from `edtslib/util.py` | Python 3 only, sectors as absolute index tuples, only the functions the plugin needs, plus `ha_regions_near()` |
| `__init__.py` | - | re-exports |

Every file carries a header that names its origin, the licence and the
change. The arithmetic is EDTS's, step for step.

## Checked

* `python procgen.py` (self test): sector names and indices of real
  sectors, hand-authored sectors inside and at the edge.
* `tests/named_sectors.py`: the sphere planner over hand-authored sectors.
* Against EDDiscovery's system database (read only, every 499th row, 13.11.2026):
  * 399 013 procedural systems: their sector name computes from their
    position.
  * 10 294 systems of hand-authored sectors: letters and region follow from
    the position.
  * The only misses are 2 systems of "NGC 2392 Sector", a hand-authored
    sector that EDTS's table does not list. The plugin keeps names it saw
    with a position ahead of computed ones, so such gaps in the table do
    no harm.

## Used for

`procgen.py` uses this folder for three things:

* naming sectors no known system is in;
* finding the hand-authored sectors that lie over a boxel;
* keeping wrong names out of the sector registry.

`boxelplan.py` uses it to plan probes with the name the galaxy map knows. To
update, replace `pgdata.py` from a newer EDTS revision with the same import
change, and update this note.
