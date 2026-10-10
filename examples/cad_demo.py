"""Generate three example parts without an API key; optionally render snapshots.

Usage: python examples/cad_demo.py [--snapshot | --preview]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from roboforge.cad.engine import build, root_directory
from roboforge.cad.spec import PartSpec


def preview_step(directory: Path, name: str):
    """Offline polygon preview of the saved STEP when a browser is unavailable."""
    from cadgen import build123d as bd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    shape = bd.import_step(str(directory / "STEP/part.step"))
    vertices, triangles = shape.tessellate(0.1)
    points = [(vertex.X, vertex.Y, vertex.Z) for vertex in vertices]
    polygons = [[points[index] for index in triangle] for triangle in triangles]
    figure = plt.figure(figsize=(10, 7))
    axes = figure.add_subplot(111, projection="3d")
    axes.add_collection3d(Poly3DCollection(polygons, facecolors="#8dc5dc", shade=True))
    bounds = shape.bounding_box()
    axes.set_xlim(bounds.min.X - 5, bounds.max.X + 5)
    axes.set_ylim(bounds.min.Y - 5, bounds.max.Y + 5)
    axes.set_zlim(bounds.min.Z - 3, bounds.max.Z + 3)
    axes.set_box_aspect((bounds.size.X, bounds.size.Y, max(bounds.size.Z, 12)))
    axes.set_xlabel("X (mm)")
    axes.set_ylabel("Y (mm)")
    axes.set_zlabel("Z (mm)")
    axes.set_title(f"{name} — saved STEP preview")
    axes.view_init(elev=28, azim=-55)
    figure.savefig(directory / "review.png", dpi=120, bbox_inches="tight")
    plt.close(figure)


def main():
    environment = {**os.environ, "CADGEN_TELEMETRY": "0", "CADGEN_UPDATE_CHECK": "0", "CADGEN_DAEMON": "0"}
    for spec in (
        PartSpec(name="Chassis plate", kind="chassis_plate", length_mm=220, width_mm=160, thickness_mm=5),
        PartSpec(name="Arm link", kind="arm_link", length_mm=160, width_mm=30, thickness_mm=6),
        PartSpec(name="Motor bracket", kind="motor_bracket", length_mm=60, width_mm=50,
                 thickness_mm=4, bracket_height_mm=45),
    ):
        result = build(spec)
        directory = root_directory() / result["design_id"]
        if "--snapshot" in sys.argv:
            cadgen = Path(sys.executable).parent / ("cadgen.exe" if os.name == "nt" else "cadgen")
            subprocess.run([str(cadgen), "step", "snapshot", str(directory / "STEP/part.step"),
                            str(directory / "review.png"), "--size-profile", "simple"],
                           check=True, timeout=300, env=environment)
        elif "--preview" in sys.argv:
            preview_step(directory, spec.name)
        print(json.dumps({"part": spec.name, "directory": str(directory),
                          "geometry": result["geometry"], "cached": result["cached"]}), flush=True)


if __name__ == "__main__":
    main()
