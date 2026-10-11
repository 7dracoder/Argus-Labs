"""In-memory versioned project store. Swap for Supabase/PostgreSQL later."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from roboforge.models import RobotProject


class ProjectStore:
    def __init__(self) -> None:
        self._history: dict[str, list[RobotProject]] = {}
        self._lock = Lock()

    def create(self, project: RobotProject) -> RobotProject:
        with self._lock:
            self._history[project.id] = [project.model_copy(deep=True)]
        return project

    def get(self, project_id: str, revision: int | None = None) -> RobotProject | None:
        revisions = self._history.get(project_id)
        if not revisions:
            return None
        if revision is None:
            return revisions[-1].model_copy(deep=True)
        if 1 <= revision <= len(revisions):
            return revisions[revision - 1].model_copy(deep=True)
        return None

    def save_revision(self, project: RobotProject, *, expected_revision: int | None = None) -> RobotProject:
        """Persist an edited project as a new revision."""
        with self._lock:
            revisions = self._history[project.id]
            if expected_revision is not None and revisions[-1].revision != expected_revision:
                raise ValueError("The robot changed while this edit was being prepared. Reload the current revision and retry.")
            project.revision = revisions[-1].revision + 1
            project.updated_at = datetime.now(timezone.utc)
            revisions.append(project.model_copy(deep=True))
        return project

    def list(self) -> list[RobotProject]:
        return [r[-1] for r in self._history.values()]


store = ProjectStore()
