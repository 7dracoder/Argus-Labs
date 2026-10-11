"""Subprocess entry point: generate exports and independently inspect saved STEP."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from roboforge.cad.spec import PartSpec


# This is fixed source. User and model values live exclusively in spec.json.
MODEL_SOURCE = '''from pathlib import Path
from cadgen import step, stl, glb
from roboforge.cad.spec import PartSpec
from roboforge.cad.templates import build_part

@step(out="../STEP/part.step")
@stl(out="../STL/part.stl")
@glb(out="../GLB/part.glb")
def part():
    spec = PartSpec.model_validate_json((Path(__file__).parent.parent / "spec.json").read_text())
    return build_part(spec)

if __name__ == "__main__":
    part()
'''


def inspect_step(path: Path, spec: PartSpec) -> dict:
    # Read exported bytes through the CAD kernel rather than trusting the model's return.
    from cadgen import build123d as bd

    from roboforge.cad.templates import (
        expected_envelope, expected_volume, hole_positions, mounting_hole_diameter,
    )

    shape = bd.import_step(str(path))
    solids = shape.solids()
    bounds = shape.bounding_box().size
    expected = expected_envelope(spec)
    measured = [bounds.X, bounds.Y, bounds.Z]
    dims_ok = all(abs(a - b) <= 0.01 for a, b in zip(expected, measured))
    radius = mounting_hole_diameter(spec) / 2
    centers = hole_positions(spec)
    expected_volume_mm3 = expected_volume(spec)
    actual_volume = shape.volume
    volume_ok = abs(actual_volume - expected_volume_mm3) <= max(0.05, expected_volume_mm3 * 1e-5)
    # Inspect circular rim edges in the saved STEP: two per through-hole on the base plane.
    # Wheel hubs also have an axle bore (different diameter) that is checked separately.
    base_top_z = spec.thickness_mm
    expected_rims = [(a, b, z) for a, b in centers for z in (0, base_top_z)]
    rims = [edge for edge in shape.edges() if edge.geom_type == bd.GeomType.CIRCLE]
    holes_ok = all(
        any(abs(edge.radius - radius) <= 0.01 and
            max(abs(edge.arc_center.X - a), abs(edge.arc_center.Y - b),
                abs(edge.arc_center.Z - z)) <= 0.01 for edge in rims)
        for a, b, z in expected_rims
    )
    if spec.kind == "wheel_hub":
        axle_r = spec.hole_diameter_mm / 2
        collar_h = max(3.0, spec.thickness_mm * 0.45)
        axle_ok = all(
            any(abs(edge.radius - axle_r) <= 0.01 and
                max(abs(edge.arc_center.X), abs(edge.arc_center.Y),
                    abs(edge.arc_center.Z - z)) <= 0.01 for edge in rims)
            for z in (0, spec.thickness_mm + collar_h)
        )
        holes_ok = holes_ok and axle_ok
    checks = {"valid_brep": bool(shape.is_valid), "single_solid": len(solids) == 1,
              "positive_volume": bool(solids) and all(s.volume > 0 for s in solids),
              "envelope_dimensions": dims_ok, "bore_volume": volume_ok,
              "mounting_hole_pattern": holes_ok}
    if not all(checks.values()):
        raise ValueError(f"Exported STEP failed geometry checks: {checks}")
    density = {"petg": 1.27e-6, "pla": 1.24e-6, "aluminum": 2.70e-6}[spec.material]
    return {
        "status": "pass", "checks": checks, "units": "mm",
        "bounds_mm": [round(x, 6) for x in measured],
        "dimension_tolerance_mm": 0.01, "volume_mm3": round(actual_volume, 6),
        "mounting_holes": len(centers), "hole_diameter_mm": mounting_hole_diameter(spec),
        "mass_kg": round(actual_volume * density, 6),
        "mass_assumption": "Uniform solid material; printed infill and hardware excluded.",
        "untested": ["structural load", "motor fit", "assembly clearance", "printability", "physical operation"],
    }


def main():
    directory = Path(sys.argv[1]).resolve()
    spec = PartSpec.model_validate_json((directory / "spec.json").read_text())
    source = directory / "src" / "part.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(MODEL_SOURCE, encoding="utf-8")
    subprocess.run([sys.executable, str(source), "--json"], check=True, timeout=150)
    report = inspect_step(directory / "STEP" / "part.step", spec)
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
