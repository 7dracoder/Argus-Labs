"""Tiger Data telemetry storage with a safe in-memory development fallback."""
from __future__ import annotations

import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    observed_at: datetime = Field(default_factory=_now)
    scenario_id: str = Field(default="default", min_length=1, max_length=120)
    metric: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    value: float
    unit: str = Field(default="count", min_length=1, max_length=40)

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone.")
        return value.astimezone(timezone.utc)


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

    @contextmanager
    def _connect(self):
        if not self.database_url:
            raise TigerUnavailable("Set TIGER_DATABASE_URL to connect to Tiger Data.")
        try:
            import psycopg
        except ImportError as error:
            raise TigerUnavailable(
                "Install the optional Tiger dependency: pip install -e '.[integrations]'"
            ) from error
        try:
            from psycopg.conninfo import conninfo_to_dict
            settings = conninfo_to_dict(self.database_url)
            # Require encryption for remote services, even if the URI omits SSL.
            local = settings.get("host") in {"localhost", "127.0.0.1", "::1"}
            if not local:
                if settings.get("sslmode", "require") not in {"require", "verify-ca", "verify-full"}:
                    raise TigerUnavailable("Remote Tiger connections require sslmode=require or certificate verification.")
                settings.setdefault("sslmode", "require")
            settings.update(connect_timeout=10, application_name="roboforge")
            with psycopg.connect(**settings) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                yield connection
        except (psycopg.Error, ValueError):
            # Driver messages can contain hosts, users, and database credentials.
            raise TigerUnavailable("Tiger database operation failed. Check connection credentials, network access, and run setup.") from None

    def health(self) -> dict:
        if not self.database_url:
            return {"configured": False, "connected": False, "schema_ready": False,
                    "mode": "memory", "action": "Set TIGER_DATABASE_URL in .env and run Tiger setup."}
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
                extension = cursor.fetchone()
                cursor.execute("SELECT to_regclass('public.roboforge_telemetry'), to_regclass('public.roboforge_telemetry_1m')")
                tables = cursor.fetchone()
            return {"configured": True, "connected": True, "mode": "tiger",
                    "timescaledb_version": extension[0] if extension else None,
                    "schema_ready": bool(extension and tables and all(tables))}
        except TigerUnavailable as error:
            return {"configured": True, "connected": False, "schema_ready": False,
                    "mode": "tiger", "error": str(error)}

    def initialize(self) -> None:
        """Create the time-series table and its Tiger hypertable once."""
        statements = [
            "CREATE EXTENSION IF NOT EXISTS timescaledb",
            """
            CREATE TABLE IF NOT EXISTS public.roboforge_telemetry (
                observed_at TIMESTAMPTZ NOT NULL,
                project_id TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                value DOUBLE PRECISION NOT NULL,
                unit TEXT NOT NULL
            )
            """,
            "SELECT create_hypertable('public.roboforge_telemetry', 'observed_at', if_not_exists => TRUE)",
            """
            CREATE INDEX IF NOT EXISTS roboforge_telemetry_project_time_idx
            ON public.roboforge_telemetry (project_id, observed_at DESC)
            """,
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS public.roboforge_telemetry_1m
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 minute', observed_at) AS bucket,
                   project_id, scenario_id, metric, unit,
                   AVG(value) AS average_value,
                   MAX(value) AS maximum_value,
                   MIN(value) AS minimum_value,
                   COUNT(*) AS samples
            FROM public.roboforge_telemetry
            GROUP BY bucket, project_id, scenario_id, metric, unit
            WITH NO DATA
            """,
            "ALTER MATERIALIZED VIEW public.roboforge_telemetry_1m SET (timescaledb.materialized_only = false)",
            """
            SELECT add_continuous_aggregate_policy('public.roboforge_telemetry_1m',
                start_offset => INTERVAL '1 day', end_offset => INTERVAL '1 minute',
                schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE)
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
                    INSERT INTO public.roboforge_telemetry
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
            FROM public.roboforge_telemetry WHERE project_id = %s
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

    def timeseries(self, project_id: str, since: datetime, scenario_id: str | None = None,
                   limit: int = 300) -> dict:
        if not self.database_url:
            with self._lock:
                events = list(self._events[project_id])
            grouped = defaultdict(list)
            for event in events:
                if event.observed_at < since or (scenario_id and event.scenario_id != scenario_id):
                    continue
                bucket = event.observed_at.replace(second=0, microsecond=0)
                grouped[(bucket, event.scenario_id, event.metric, event.unit)].append(event.value)
            rows = [(bucket, scenario, metric, unit, sum(values)/len(values), min(values), max(values), len(values))
                    for (bucket, scenario, metric, unit), values in grouped.items()]
            rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]), reverse=True)
            rows = rows[:limit]
        else:
            query = """SELECT bucket, scenario_id, metric, unit, average_value,
                       minimum_value, maximum_value, samples FROM public.roboforge_telemetry_1m
                       WHERE project_id = %s AND bucket >= %s"""
            values = [project_id, since]
            if scenario_id:
                query += " AND scenario_id = %s"
                values.append(scenario_id)
            query += " ORDER BY bucket DESC, scenario_id DESC, metric DESC, unit DESC LIMIT %s"
            values.append(limit)
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(query, values)
                rows = cursor.fetchall()
        return {"storage": self.mode, "bucket_seconds": 60, "points": [
            {"bucket": row[0], "scenario_id": row[1], "metric": row[2], "unit": row[3],
             "average": round(float(row[4]), 4), "minimum": float(row[5]),
             "maximum": float(row[6]), "samples": int(row[7])} for row in reversed(rows)]}

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
