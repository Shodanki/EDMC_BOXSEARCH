"""
Science report for one body - what a ship's science officer would be told.

Rule based, from fixed text building blocks: no AI. The server returns facts
as (section, id, values, level); the browser words them in the display
language (web/js/views/planet.js, table REPORT). Sections in reading order:

  class       what it is (class, size, mass, gravity / star type, age)
  record      who was first (as far as the journal knows: you or someone)
  atmosphere  atmosphere, pressure, temperature, rotation
  geology     volcanism, geological signals
  biology     signals, analysed species, genera still open, forecast
  resources   notable materials (jumponium, rare grade 4), rings and hotspots
  hazards     gravity, temperature, atmosphere, star types to keep away from
  advice      what to do here (DSS, landing, sampling, scooping)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# FSD injection (jumponium) recipes - the raw materials of the game's recipes
JUMPONIUM = {
    "basic": ("carbon", "vanadium", "germanium"),
    "standard": ("carbon", "vanadium", "germanium", "cadmium", "niobium"),
    "premium": ("carbon", "germanium", "arsenic", "niobium", "yttrium", "polonium"),
}
RARE_RAW = ("antimony", "polonium", "ruthenium", "technetium", "tellurium", "yttrium")
VALUABLE = ("Earthlike body", "Water world", "Ammonia world")
TOXIC_ATMO = ("ammonia", "sulphurdioxide", "sulphur dioxide", "methane", "neon")

HIGH_G = 2.0
VERY_HIGH_G = 3.0
HOT_K = 800.0
COLD_K = 60.0


def _f(section: str, key: str, level: str = "info", **v: Any) -> Dict[str, Any]:
    return {"section": section, "id": key, "level": level, "v": v}


def body_report(b: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`b` is the PLANET INFO record (fis.model.build_body)."""
    out: List[Dict[str, Any]] = []
    star = b.get("star")
    g = b.get("gravity_g")
    t = b.get("temp_k")
    flags = b.get("flags") or {}
    bio = b.get("bio") or {}

    # ---- class
    if star:
        out.append(_f("class", "star", t=(star.get("type") or "?") + str(star.get("subclass") or ""),
                      lum=star.get("luminosity") or "", m=star.get("mass_sol"), age=star.get("age_my")))
    elif b.get("kind") == "Planet":
        out.append(_f("class", "planet", cls=b.get("cls") or "?", r=b.get("radius_km"),
                      m=b.get("mass_em"), g=g))
        if b.get("parent"):
            out.append(_f("class", "orbits", p=b["parent"]))
        if b.get("terraform") == "Terraformable":
            out.append(_f("class", "terraformable", level="good"))
    # ---- discovery record
    if flags.get("first"):
        out.append(_f("record", "first_discovery", level="good"))
    elif b.get("was_discovered") is True:
        out.append(_f("record", "known_before"))
    if flags.get("first_map"):
        out.append(_f("record", "first_mapped", level="good"))
    if flags.get("footfall"):
        out.append(_f("record", "first_footfall_open", level="good"))
    dss = b.get("dss")
    if dss and dss.get("probes") is not None:
        out.append(_f("record", "dss_efficient" if dss.get("efficient") else "dss_done",
                      level="good" if dss.get("efficient") else "info",
                      p=dss["probes"], target=dss.get("target")))
    # ---- atmosphere and surface
    if not star:
        if b.get("atmosphere") or (b.get("atmo_type") and b.get("atmo_type") != "None"):
            out.append(_f("atmosphere", "atmosphere", a=b.get("atmosphere") or b.get("atmo_type"),
                          p=b.get("pressure_atm")))
        else:
            out.append(_f("atmosphere", "no_atmosphere"))
        if t is not None:
            out.append(_f("atmosphere", "temperature", k=t, c=round(t - 273.15)))
        if b.get("tidal_lock"):
            out.append(_f("atmosphere", "tidal_lock"))
        elif b.get("rotation_d"):
            out.append(_f("atmosphere", "rotation", d=b.get("rotation_d")))
    # ---- geology
    if not star:
        if b.get("volcanism"):
            out.append(_f("geology", "volcanism", v=b["volcanism"]))
        elif b.get("kind") == "Planet" and b.get("landable"):
            out.append(_f("geology", "no_volcanism"))
        if bio.get("geo"):
            out.append(_f("geology", "geo_signals", n=bio["geo"]))
    # ---- biology
    sig, done = int(bio.get("signals") or 0), len(bio.get("species") or [])
    if sig:
        out.append(_f("biology", "bio_signals", n=sig, a=done))
        open_genera = [gn for gn in bio.get("genera") or []
                       if gn not in {s.get("genus") for s in bio.get("species") or []}]
        if open_genera:
            out.append(_f("biology", "bio_open", level="warn", g=", ".join(open_genera)))
        elif not bio.get("genera") and bio.get("prediction"):
            top = bio["prediction"][0]
            out.append(_f("biology", "bio_forecast", g=top.get("genus"), p=round(100 * (top.get("score") or 0))))
    # ---- resources
    mats = {k.lower(): v for k, v in (b.get("materials") or [])}
    rare = [m for m in RARE_RAW if m in mats]
    if rare:
        out.append(_f("resources", "rare_materials", level="good",
                      m=", ".join("%s %.1f %%" % (m.capitalize(), mats[m]) for m in rare)))
    for grade in ("premium", "standard", "basic"):
        if all(m in mats for m in JUMPONIUM[grade]):
            out.append(_f("resources", "jumponium_" + grade, level="good"))
            break
    if b.get("rings"):
        out.append(_f("resources", "rings", n=len(b["rings"]),
                      r=b.get("reserve") or "", c=", ".join(sorted({r.get("cls") or "?" for r in b["rings"]}))))
    if b.get("hotspots"):
        out.append(_f("resources", "hotspots", level="good",
                      h=", ".join("%s ×%s" % (h["material"], h["count"]) for h in b["hotspots"][:4])))
    # ---- hazards
    if g is not None and g >= VERY_HIGH_G and b.get("landable"):
        out.append(_f("hazards", "gravity_very_high", level="danger", g=g))
    elif g is not None and g >= HIGH_G and b.get("landable"):
        out.append(_f("hazards", "gravity_high", level="warn", g=g))
    if t is not None and not star and t >= HOT_K:
        out.append(_f("hazards", "hot", level="warn", k=t))
    elif t is not None and not star and t <= COLD_K and b.get("landable"):
        out.append(_f("hazards", "cold", level="warn", k=t))
    atmo = (b.get("atmosphere") or "").lower().replace(" ", "")
    if b.get("landable") and any(x.replace(" ", "") in atmo for x in TOXIC_ATMO):
        out.append(_f("hazards", "toxic", level="warn", a=b.get("atmosphere")))
    if star:
        st = (star.get("type") or "")
        if st == "N":
            out.append(_f("hazards", "neutron", level="danger"))
        elif st.startswith("D"):
            out.append(_f("hazards", "white_dwarf", level="danger"))
        elif st in ("H", "SupermassiveBlackHole"):
            out.append(_f("hazards", "black_hole", level="danger"))
    # ---- advice
    if star:
        out.append(_f("advice", "scoopable" if star.get("scoopable") else "not_scoopable",
                      level="good" if star.get("scoopable") else "warn"))
    elif b.get("kind") == "Planet":
        valuable = b.get("cls") in VALUABLE or b.get("terraform") == "Terraformable"
        if not flags.get("mapped") and (valuable or sig):
            out.append(_f("advice", "dss_recommended", level="warn",
                          why="bio" if sig and not valuable else "value"))
        if b.get("landable"):
            out.append(_f("advice", "landing", g=g, level="warn" if g and g >= HIGH_G else "info"))
        if sig and done < sig:
            out.append(_f("advice", "sample", n=sig - done, level="warn"))
        if sig and done >= sig:
            out.append(_f("advice", "bio_complete", level="good"))
    return out


def worst(report: List[Dict[str, Any]]) -> str:
    order = {"danger": 3, "warn": 2, "good": 1, "info": 0}
    return max((f["level"] for f in report), key=lambda lv: order.get(lv, 0), default="info")
