"""Tiger Data telemetry storage with a safe in-memory development fallback."""
from __future__ import annotations

import os
import math
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

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
    def __init__(self, message: str, code: str = "unavailable", retry_after: int = 0):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def _database_error(error) -> TigerUnavailable:
    """Classify errors without ever returning driver text/credentials."""
    state = getattr(error, "sqlstate", None)
    text = str(error).lower()
    if state in {"28P01", "28000"} or "password authentication failed" in text:
        return TigerUnavailable("Tiger rejected authentication. Check TIGER_DATABASE_URL in .env and restart the backend.", "authentication_failed")
    if state == "42501":
        return TigerUnavailable("The Tiger database role lacks permission for this operation.", "permission_denied")
    if state in {"42P01", "42883"}:
        return TigerUnavailable("Tiger telemetry schema is missing. Run Tiger schema setup.", "schema_missing")
    if state == "57014":
        return TigerUnavailable("The Tiger query exceeded its statement time limit.", "query_timeout")
    if "timeout" in text or "timed out" in text:
        return TigerUnavailable("Tiger connection timed out before a database session was established. Check service readiness and PostgreSQL network access.", "connection_timeout")
    if "resolve" in text or "name or service" in text or "getaddrinfo" in text:
        return TigerUnavailable("The Tiger hostname could not be resolved. Check the connection URL and DNS/network access.", "dns_failed")
    if "certificate" in text or "ssl" in text or "tls" in text:
        return TigerUnavailable("Tiger TLS negotiation failed. Keep SSL enabled and verify the endpoint and certificate settings.", "tls_failed")
    return TigerUnavailable("Tiger database operation failed. Check connection credentials, network access, and run setup.", "connection_failed")


class TigerTelemetry:
    """Writes to Tiger Cloud/PostgreSQL when TIGER_DATABASE_URL is configured."""

    def __init__(self) -> None:
        self.database_url = os.environ.get("TIGER_DATABASE_URL")
        self._events: dict[str, list[TelemetryEvent]] = defaultdict(list)
        self._lock = Lock()
        self._connect_lock = Lock()
        self._address_offset = 0
        self._retry_at = 0.0
        self._last_connect_error: TigerUnavailable | None = None

    def _open_connection(self, settings, psycopg, *, retry=False):
        # psycopg's connect_timeout applies to EACH resolved address. Tiger's
        # endpoint currently has six, which turned a "10s" check into ~60s.
        # Resolve once, preserve host for TLS/SNI, and give all attempts a shared
        # budget. Rotate the first candidate on the next check for failover.
        from psycopg.conninfo import conninfo_attempts
        with self._connect_lock:
            if not retry and self._last_connect_error and monotonic() < self._retry_at:
                error = self._last_connect_error
                raise TigerUnavailable(str(error), error.code, math.ceil(self._retry_at - monotonic()))
            try:
                attempts = conninfo_attempts(settings)
                offset = self._address_offset % len(attempts)
                self._address_offset += 1
                attempts = attempts[offset:] + attempts[:offset]
                deadline = monotonic() + 8
                last_error = psycopg.errors.ConnectionTimeout("connection timeout expired")
                for attempt in attempts:
                    # libpq enforces a minimum 2-second timeout. Don't start an
                    # attempt when there is less than that remaining.
                    if deadline - monotonic() < 2:
                        break
                    try:
                        connection = psycopg.connect(**{**attempt, "connect_timeout": 2})
                    except psycopg.OperationalError as error:
                        if getattr(error, "sqlstate", None):
                            raise
                        last_error = error
                    else:
                        self._last_connect_error = None
                        self._retry_at = 0
                        return connection
                raise last_error
            except psycopg.Error as error:
                safe = _database_error(error)
                self._last_connect_error = safe
                self._retry_at = monotonic() + 15
                raise TigerUnavailable(str(safe), safe.code, 15) from None

    @property
    def mode(self) -> str:
        return "tiger" if self.database_url else "memory"

    @contextmanager
    def _connect(self, *, retry=False):
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
            settings.update(application_name="roboforge")
            with self._open_connection(settings, psycopg, retry=retry) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                yield connection
        except (psycopg.Error, ValueError) as error:
            # Driver messages can contain hosts, users, and database credentials.
            raise _database_error(error) from None

    def health(self, *, retry=False) -> dict:
        if not self.database_url:
            return {"configured": False, "connected": False, "schema_ready": False,
                    "mode": "memory", "action": "Set TIGER_DATABASE_URL in .env and run Tiger setup."}
        try:
            with self._connect(retry=retry) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
                extension = cursor.fetchone()
                cursor.execute("SELECT to_regclass('public.roboforge_telemetry'), to_regclass('public.roboforge_telemetry_1m')")
                tables = cursor.fetchone()
            ready = bool(extension and tables and all(tables))
            return {"configured": True, "connected": True, "mode": "tiger",
                    "timescaledb_version": extension[0] if extension else None,
                    "schema_ready": ready,
                    "action": None if ready else "Initialize the Tiger telemetry schema."}
        except TigerUnavailable as error:
            return {"configured": True, "connected": False, "schema_ready": False,
                    "mode": "tiger", "error": str(error), "error_code": error.code,
                    "retry_after_seconds": error.retry_after,
                    "action": "Check the Tiger service and network access, then retry. Do not disable SSL."}

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
