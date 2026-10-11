"""Explicit prototype dimensions shared by sizing, assembly and edit parsing."""
from dataclasses import replace
import re

from roboforge.models import Requirements

DIMENSIONS = ("body_length_mm", "body_width_mm", "mast_height_mm", "arm_link_length_mm", "wheel_diameter_mm")
UNITS = r"(millimeters?|millimetres?|mm|centimeters?|centimetres?|cm|meters?|metres?|m|inches|inch|in)\b"
FACTORS = {"mm": 1, "cm": 10, "m": 1000, "in": 25.4}


def millimeters(value, unit):
    unit = unit.lower()
    key = "mm" if unit.startswith("mill") else "cm" if unit.startswith("cent") else "in" if unit.startswith("in") else "m" if unit.startswith("met") else unit
    return round(float(value) * FACTORS[key], 3)


def parse_dimensions(text: str) -> dict:
    """Extract only explicitly labeled dimensions. Never guess missing units."""
    text = text.lower()
    result = {}
    pair = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)\s*" + UNITS, text)
    if pair and any(w in text for w in ("body", "base", "robot", "chassis", "footprint")):
        result.update(body_length_mm=millimeters(pair[1], pair[3]), body_width_mm=millimeters(pair[2], pair[3]))
    names = {"body_length_mm": r"(?:body\s+|base\s+|chassis\s+)?length|long",
             "body_width_mm": r"(?:body\s+|base\s+|chassis\s+)?width|wide",
             "mast_height_mm": r"mast(?:\s+height)?|neck(?:\s+height)?",
             "arm_link_length_mm": r"arm\s+link(?:\s+length)?|link\s+length",
             "wheel_diameter_mm": r"wheel(?:s)?(?:\s+diameter)?"}
    for field, name in names.items():
        if field in {"body_length_mm", "body_width_mm"} and any(part in text for part in ("arm link", "motor bracket", "deck plate", "chassis plate", "cover")) and not re.search(r"\b(?:body|base|robot)\s+(?:length|width|long|wide)\b", text):
            continue
        match = re.search(r"\b(?:" + name + r")\s*(?:to|of|is|at|=|:)?\s*(\d+(?:\.\d+)?)\s*" + UNITS, text)
        reverse = re.search(r"(\d+(?:\.\d+)?)\s*" + UNITS + r"\s*(?:" + name + r")\b", text)
        if match:
            result[field] = millimeters(match[1], match[2])
        elif reverse:
            result[field] = millimeters(reverse[1], reverse[2])
    area = re.search(r"(?:operating|working|work|room|floor)\s+area\s*(?:to|of|is|=|:)?\s*(\d+(?:\.\d+)?)\s*(?:m2|m²|square\s+met(?:er|re)s?)", text)
    if area:
        result["operating_area_m2"] = float(area[1])
    return result


def apply_dimensions(arch, req: Requirements):
    length = req.body_length_mm / 1000 if req.body_length_mm is not None else arch.size_m[0]
    width = req.body_width_mm / 1000 if req.body_width_mm is not None else arch.size_m[1]
    if arch.base == "round" and (req.body_length_mm is None) != (req.body_width_mm is None):
        length = width = length if req.body_length_mm is not None else width
    if arch.base == "round" and abs(length - width) > .001:
        raise ValueError("This round body needs equal length and width. Choose a rectangular body plan for a rectangular footprint.")
    if req.wheel_diameter_mm is not None and arch.track:
        raise ValueError("A tracked robot has tracks, not wheels. Change the body plan before setting wheel diameter.")
    return replace(arch, size_m=(length, width),
                   mast_m=req.mast_height_mm / 1000 if req.mast_height_mm is not None else arch.mast_m,
                   wheel_mm=req.wheel_diameter_mm if req.wheel_diameter_mm is not None else arch.wheel_mm)
