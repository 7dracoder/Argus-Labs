"""Restart a localhost preview without losing its in-memory project revisions.

Capture before stopping the old server, then start with --restore. Snapshots are
local project data (not configuration or credentials), under ignored artifacts/.
This is a development helper, not a production persistence system.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import uvicorn

from roboforge.models import RobotProject
from roboforge.store import store

ROOT = Path(__file__).resolve().parents[1]


def validate_history(raw: dict) -> dict[str, list[RobotProject]]:
    history = {}
    for project_id, revisions in raw.items():
        models = [RobotProject.model_validate(revision) for revision in revisions]
        if not models or any(p.id != project_id or p.revision != i
                             for i, p in enumerate(models, start=1)):
            raise ValueError("Snapshot has inconsistent project revisions")
        history[project_id] = models
    return history


def capture(url: str, destination: Path) -> dict[str, list[RobotProject]]:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
        raise ValueError("Only a credential-free localhost preview may be captured")
    history = {}
    with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        response = client.get("/projects")
        response.raise_for_status()
        for project in response.json():
            revisions = []
            for revision in range(1, project["revision"] + 1):
                response = client.get(f"/projects/{project['id']}", params={"revision": revision})
                response.raise_for_status()
                revisions.append(response.json())
            history[project["id"]] = revisions
            response = client.get(f"/projects/{project['id']}")
            response.raise_for_status()
            if response.json() != revisions[-1]:
                raise ValueError("Project changed during capture; retry before restarting")
    validated = validate_history(history)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an earlier recovery snapshot.
    with destination.open("x", encoding="utf-8") as output:
        json.dump(history, output, indent=2)
    return validated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--capture", metavar="LOCAL_URL")
    mode.add_argument("--restore", action="store_true")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    state = args.state.resolve()
    if not state.is_relative_to(ROOT / "artifacts"):
        parser.error("Recovery snapshots must be under this workspace's artifacts directory")
    if args.capture:
        history = capture(args.capture, state)
        print(json.dumps({"snapshot": str(state), "projects": len(history),
                          "revisions": sum(map(len, history.values()))}), flush=True)
        return
    if args.restore:
        history = validate_history(json.loads(state.read_text(encoding="utf-8")))
        with store._lock:
            store._history = history
        print(json.dumps({"restored_projects": len(history),
                          "revisions": sum(map(len, history.values()))}), flush=True)
    uvicorn.run("roboforge.main:app", host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
