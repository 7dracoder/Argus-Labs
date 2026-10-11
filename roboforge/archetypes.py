"""Robot body plans. A brief is classified into one archetype, which decides the
chassis shape, drive train, default modules and runtime, so different jobs give
genuinely different robots (not the same parts list with a new name)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


@lru_cache(maxsize=512)
def _pattern(word: str) -> re.Pattern:
    w = re.escape(word)
    if len(word) <= 4:  # short words must be whole words: "arm" not "farm", "tow" not "towel"
        return re.compile(rf"\b{w}{re.escape(word[-1])}?(s|es|ed|ing|er|ers)?\b")
    return re.compile(rf"\b{w}")


def has_word(text: str, word: str) -> bool:
    return bool(_pattern(word).search(text))


def has_any(text: str, words) -> bool:
    return any(has_word(text, w) for w in words)


@dataclass(frozen=True)
class Archetype:
    key: str
    label: str
    base: str                      # rect | low | round | plate
    size_m: tuple[float, float]    # footprint length (x) and width (z)
    body_h_m: float
    base_mass_kg: float            # robot mass excluding payload, for sizing
    wheels: int = 2                # 0 = stationary; tracks use `track`
    track: bool = False
    wheel_mm: int = 100            # preferred wheel diameter
    arm: bool = False
    nav_lidar: bool = False        # lidar included in the minimum build
    runtime_h: float = 2.0
    compute: str = "raspberry-pi-5"
    modules: tuple[str, ...] = ()  # catalog kinds added to the minimum build
    camera: str = "mast"           # mast | front | head | pan_tilt | post
    mast_m: float = 0.0
    blurb: str = ""
    keywords: tuple[str, ...] = field(default=())


ARCHETYPES: dict[str, Archetype] = {a.key: a for a in (
    Archetype("mobile_manipulator", "Mobile manipulator", "rect", (0.42, 0.34), 0.09, 6, wheels=2, wheel_mm=100,
              arm=True, camera="mast", mast_m=0.42,
              blurb="Wheeled base with a 5-joint arm and a camera mast for picking and fetching."),
    Archetype("delivery_rover", "Delivery rover", "rect", (0.58, 0.44), 0.14, 9, wheels=4, wheel_mm=150,
              nav_lidar=True, runtime_h=4, compute="jetson-orin-nano", modules=("cargo_bin", "lights"),
              camera="front", blurb="Sidewalk-style rover: four pneumatic wheels, lockable cargo bin, lights.",
              keywords=("deliver", "package", "parcel", "courier", "mail", "drop off", "groceries", "food",
                        "follow me", "follows me", "suitcase", "luggage", "medicine", "room service", "construction",
                        "job site", "jobsite", "worksite", "carry tools", "haul")),
    Archetype("warehouse_amr", "Warehouse AMR", "low", (0.74, 0.54), 0.16, 18, wheels=4, wheel_mm=150,
              nav_lidar=True, runtime_h=4, compute="jetson-orin-nano", modules=("lift", "lights"),
              camera="front", blurb="Low autonomous mobile robot with a lifting top plate for totes and shelves.",
              keywords=("warehouse", "pallet", "shelf", "shelves", "tote", "cart", "inventory", "logistics", "tow",
                        "heavy", "fulfil", "distribution center", "distribution centre")),
    Archetype("cleaning_robot", "Cleaning robot", "round", (0.34, 0.34), 0.085, 3, wheels=2, wheel_mm=65,
              nav_lidar=True, runtime_h=1.5, modules=("vacuum", "side_brush", "proximity"), camera="front",
              blurb="Round low-profile vacuum with side brushes, bumper sensors and a lidar turret.",
              keywords=("clean", "vacuum", "sweep", "mop", "dust", "crumbs", "floor care")),
    Archetype("telepresence", "Telepresence companion", "round", (0.40, 0.40), 0.12, 7, wheels=2, wheel_mm=100,
              nav_lidar=True, runtime_h=4, compute="jetson-orin-nano", modules=("display", "speaker"),
              camera="head", mast_m=0.95,
              blurb="Tall, slim robot with a screen head, camera, speakers and microphones.",
              keywords=("telepresence", "video call", "companion", "greet", "reception", "guide", "elderly",
                        "concierge", "screen", "remote visit", "kids", "children", "child", "story", "stories",
                        "play with", "keep company", "lonely", "chat with", "tutor", "teach")),
    Archetype("security_patrol", "Patrol & inspection robot", "round", (0.46, 0.46), 0.16, 9, wheels=2, wheel_mm=100,
              nav_lidar=True, runtime_h=4, compute="jetson-orin-nano", modules=("pan_tilt", "lights", "speaker"),
              camera="pan_tilt", mast_m=0.7,
              blurb="Patrol and inspection robot: tall sensor tower with a pan-tilt camera, lidar, lights and a speaker.",
              keywords=("security", "patrol", "guard", "night watch", "surveil", "intruder", "watchman",
                        "monitor the", "keep watch", "inspect", "gauge", "meter reading", "leak", "thermal")),
    Archetype("tracked_explorer", "Tracked explorer", "rect", (0.56, 0.42), 0.12, 10, track=True, wheels=0,
              runtime_h=3, compute="jetson-orin-nano", modules=("pan_tilt", "lights"), camera="pan_tilt",
              blurb="Rugged tracked chassis with a pan-tilt camera head for rough ground.",
              keywords=("outdoor", "garden", "farm", "field", "rough", "terrain", "explore", "mud",
                        "gravel", "yard", "backyard", "snow", "lawn", "grass", "forest", "trail", "search and rescue",
                        "rubble", "mow")),
    Archetype("stationary_arm", "Desk robot arm", "plate", (0.30, 0.30), 0.03, 3, wheels=0, arm=True,
              camera="post", blurb="Bench-mounted 5-joint arm with an overhead camera post.",
              keywords=("desk", "bench", "tabletop", "table-top", "stationary", "fixed", "mounted", "on a table",
                        "on the table", "countertop", "cook", "chef", "bartend", "cocktail", "mix drinks",
                        "mixes drinks", "pour", "paint", "drawing", "sketch", "solder", "assemble")),
    Archetype("mobile_robot", "Mobile robot", "rect", (0.40, 0.32), 0.09, 5, wheels=2, wheel_mm=100,
              nav_lidar=True, camera="mast", mast_m=0.32, blurb="Compact two-wheel base with sensors on a short mast."),
)}

ARM_WORDS = ("pick", "grab", "grasp", "arm", "manipulat", "fetch", "lift up", "hold", "sort", "fold", "place",
             "stack", "bring", "hand me", "fridge", "dishes", "restock",
             "stock shelves", "harvest")
INDOOR_WORDS = ("office", "house", "home", "apartment", "flat", "room", "indoor", "hospital", "hotel", "mall",
                "store", "shop", "kitchen", "hallway", "corridor", "school", "lab", "museum", "airport")
OUTDOOR_WORDS = ("outdoor", "outside", "garden", "farm", "field", "rough", "terrain", "mud", "gravel", "yard",
                 "backyard", "snow", "lawn", "grass", "forest", "trail", "rubble", "sidewalk", "street",
                 "neighbourhood", "neighborhood", "campus", "parking", "construction", "job site", "jobsite")


def open_deck_modules(arch: Archetype) -> list[str]:
    """Modules this body plan mounts on top of an open deck, so they need a printed cover."""
    if arch.base == "rect" and arch.key not in ("delivery_rover", "tracked_explorer"):
        return ["battery", "computer"]
    return ["computer"] if arch.base == "plate" else []


def classify(text: str, payload_kg: float, mobility: str | None, override: str | None = None) -> tuple[Archetype, str]:
    """Pick the body plan. Returns (archetype, reason)."""
    if override in ARCHETYPES:
        return ARCHETYPES[override], "Robot type chosen in the brief."
    if mobility == "fixed":
        return ARCHETYPES["stationary_arm"], "It stays in place, so a bench-mounted arm fits best."
    scores = {key: sum(has_word(text, word) for word in a.keywords) for key, a in ARCHETYPES.items() if a.keywords}
    if payload_kg >= 15:
        scores["warehouse_amr"] = scores.get("warehouse_amr", 0) + 2
    if has_any(text, INDOOR_WORDS) and not has_any(text, OUTDOOR_WORDS):
        scores["tracked_explorer"] -= 2  # tracks are for rough ground, not offices and homes
    wants_arm = has_any(text, ARM_WORDS)
    if wants_arm:
        # Picking jobs need an arm, which the low/round bodies can't carry.
        for key in ("cleaning_robot", "telepresence", "warehouse_amr", "delivery_rover", "security_patrol"):
            scores[key] = scores.get(key, 0) - 1
    best = max(scores, key=scores.get) if scores else None
    if best and scores[best] > 0:
        words = [w for w in ARCHETYPES[best].keywords if has_word(text, w)]
        return ARCHETYPES[best], f"Brief mentions {', '.join(words) or 'heavy loads'}."
    if wants_arm:
        return ARCHETYPES["mobile_manipulator"], "Picking and carrying tasks need a mobile base with an arm."
    return ARCHETYPES["mobile_robot"], "General-purpose task; a compact mobile base is the simplest fit."
