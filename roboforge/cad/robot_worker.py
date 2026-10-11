"""Subprocess entry point: build the whole-robot STEP and GLB from layout.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    directory = Path(sys.argv[1]).resolve()
    nodes = json.loads((directory / "layout.json").read_text())
    from cadgen import build123d as bd

    from roboforge.cad.robot import build_robot

    robot = build_robot(nodes)
    if not robot.is_valid:
        raise SystemExit("Robot compound is not a valid B-rep.")
    (directory / "STEP").mkdir(exist_ok=True)
    (directory / "GLB").mkdir(exist_ok=True)
    bd.export_step(robot, str(directory / "STEP" / "robot.step"))
    bd.export_gltf(robot, str(directory / "GLB" / "robot.glb"), binary=True,
                   linear_deflection=0.2, angular_deflection=0.3)
    size = robot.bounding_box().size
    (directory / "report.json").write_text(json.dumps({
        "parts": len(robot.children), "bounds_mm": [round(size.X, 2), round(size.Y, 2), round(size.Z, 2)],
        "note": "Catalog parts are representative models, not vendor CAD; no interference check.",
    }, indent=2))


if __name__ == "__main__":
    main()
