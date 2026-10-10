"""Tiger Data telemetry storage with a safe in-memory development fallback."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryEvent(BaseModel):
    observed_at: datetime = Field(default_factory=_now)
    scenario_id: str = Field(default="default", min_length=1, max_length=120)
    metric: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    value: float
    unit: str = Field(default="count", min_length=1, max_length=40)


class TigerUnavailable(RuntimeError):
    pass


class TigerTelemetry:
    """Writes to Tiger Cloud/PostgreSQL when TIGER_DATABASE_URL is configured."""

    def __init__(self) -> None:
        self.database_url = os.environ.get("TIGER_DATABASE_URL")
        self._events: dict[str, list[TelemetryEvent]] = defaultdict(list)
        self._lock = Lock()

    @property
    def mode(self) -> str:
        return "tiger" if self.database_url else "memory"

    def _connect(self):
        if not self.database_url:
            raise TigerUnavailable("Set TIGER_DATABASE_URL to connect to Tiger Data.")
        try:
            import psycopg
        except ImportError as error:
            raise TigerUnavailable(
                "Install the optional Tiger dependency: pip install -e '.[integrations]'"
            ) from error
        return psycopg.connect(self.database_url)

    def initialize(self) -> None:
        """Create the time-series table and its Tiger hypertable once."""
        statements = [
            """
            CREATE TABLE IF NOT EXISTS roboforge_telemetry (
                observed_at TIMESTAMPTZ NOT NULL,
                project_id TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                value DOUBLE PRECISION NOT NULL,
                unit TEXT NOT NULL
            )
            """,
            "SELECT create_hypertable('roboforge_telemetry', 'observed_at', if_not_exists => TRUE)",
            """
            CREATE INDEX IF NOT EXISTS roboforge_telemetry_project_time_idx
            ON roboforge_telemetry (project_id, observed_at DESC)
            """,
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS roboforge_telemetry_1m
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', observed_at) AS bucket,
                   project_id, scenario_id, metric, unit,
                   AVG(value) AS average_value,
                   MAX(value) AS maximum_value,
                   MIN(value) AS minimum_value,
                   COUNT(*) AS samples
            FROM roboforge_telemetry
            GROUP BY bucket, project_id, scenario_id, metric, unit
            WITH NO DATA
            """,
        ]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def record(self, project_id: str, event: TelemetryEvent) -> dict:
        if not self.database_url:
            with self._lock:
                self._events[project_id].append(event)
            return {"storage": "memory", "event": event}

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO roboforge_telemetry
                    (observed_at, project_id, scenario_id, metric, value, unit)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (event.observed_at, project_id, event.scenario_id, event.metric, event.value, event.unit),
                )
        return {"storage": "tiger", "event": event}

    def summary(self, project_id: str, scenario_id: str | None = None) -> dict:
        if not self.database_url:
            with self._lock:
                events = list(self._events[project_id])
            if scenario_id:
                events = [event for event in events if event.scenario_id == scenario_id]
            return self._summarize_memory(events)

        query = """
            SELECT metric, unit, COUNT(*) AS samples, AVG(value) AS average_value,
                   MIN(value) AS minimum_value, MAX(value) AS maximum_value
            FROM roboforge_telemetry WHERE project_id = %s
        """
        values: list[str] = [project_id]
        if scenario_id:
            query += " AND scenario_id = %s"
            values.append(scenario_id)
        query += " GROUP BY metric, unit ORDER BY metric"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, values)
                rows = cursor.fetchall()
        return {
            "storage": "tiger",
            "metrics": [
                {
                    "metric": row[0], "unit": row[1], "samples": row[2],
                    "average": round(float(row[3]), 4), "minimum": float(row[4]), "maximum": float(row[5]),
                }
                for row in rows
            ],
        }

    @staticmethod
    def _summarize_memory(events: list[TelemetryEvent]) -> dict:
        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        for event in events:
            grouped[(event.metric, event.unit)].append(event.value)
        return {
            "storage": "memory",
            "metrics": [
                {
                    "metric": metric, "unit": unit, "samples": len(values),
                    "average": round(sum(values) / len(values), 4),
                    "minimum": min(values), "maximum": max(values),
                }
                for (metric, unit), values in sorted(grouped.items())
            ],
        }


tiger = TigerTelemetry()
