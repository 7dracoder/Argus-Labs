from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Lock

from roboforge.cad.spec import PartSpec

CADGEN_VERSION = "0.7.20"
ARTIFACTS = {"step": "STEP/part.step", "stl": "STL/part.stl", "glb": "GLB/part.glb",
             "source": "src/part.py", "spec": "spec.json", "report": "report.json"}
_build_lock = Lock()


class CADUnavailable(RuntimeError):
    pass


class CADBuildFailed(RuntimeError):
    pass


def root_directory() -> Path:
    return Path(os.environ.get("ROBOFORGE_CAD_ROOT", "artifacts/cad")).resolve()


def runtime_status() -> dict:
    try:
        version = importlib.metadata.version("cadgen")
    except importlib.metadata.PackageNotFoundError:
        version = None
    from roboforge.cad.spec import PART_KINDS
    return {"configured": version == CADGEN_VERSION, "version": version,
            "required_version": CADGEN_VERSION, "templates": list(PART_KINDS)}


def build(spec: PartSpec) -> dict:
    if not runtime_status()["configured"]:
        raise CADUnavailable("Install the CAD runtime with: pip install -e '.[cad]'")
    # Code and dependency changes invalidate our cache, even with identical dimensions.
    closure = b"".join((Path(__file__).parent / f).read_bytes() for f in (
        "spec.py", "templates.py", "profiles.py", "worker.py", "engine.py"))
    normalized = spec.model_dump_json()
    design_id = hashlib.sha256(CADGEN_VERSION.encode() + closure + normalized.encode()).hexdigest()
    directory = root_directory() / design_id
    with _build_lock:
        manifest = directory / "manifest.json"
        if manifest.is_file():
            result = json.loads(manifest.read_text())
            if all((directory / ARTIFACTS[k]).is_file() and
                   hashlib.sha256((directory / ARTIFACTS[k]).read_bytes()).hexdigest() == digest
                   for k, digest in result["sha256"].items()):
                return {**result, "cached": True}
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "spec.json").write_text(normalized, encoding="utf-8")
        environment = os.environ.copy()
        # Workers have reviewed template code only. This subprocess is a timeout boundary,
        # not a sandbox for running arbitrary generated Python.
        environment.update({"CADGEN_TELEMETRY": "0", "CADGEN_UPDATE_CHECK": "0", "CADGEN_DAEMON": "0"})
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "roboforge.cad.worker", str(directory)],
                capture_output=True, text=True, timeout=180, env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise CADBuildFailed("CAD generation exceeded its 180-second timeout.") from error
        if completed.returncode:
            # Keep detailed vendor/Python errors server-side instead of returning secrets or local paths.
            import logging
            logging.getLogger(__name__).error("CAD worker failed: %s\n%s",
                                             completed.stdout[-4000:], completed.stderr[-4000:])
            raise CADBuildFailed("CAD worker failed. Check server logs for the runtime or geometry error.")
        if not all((directory / f).is_file() and (directory / f).stat().st_size for f in ARTIFACTS.values()):
            raise CADBuildFailed("CAD worker did not produce all declared artifacts.")
        result = {
            "design_id": design_id, "runtime": f"cadgen=={CADGEN_VERSION}", "spec": spec.model_dump(),
            "geometry": json.loads((directory / "report.json").read_text()),
            "sha256": {k: hashlib.sha256((directory / path).read_bytes()).hexdigest()
                       for k, path in ARTIFACTS.items()},
        }
        manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return {**result, "cached": False}
