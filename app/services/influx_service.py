"""Read-only, identity-scoped InfluxDB 1.x access."""
from datetime import datetime, timedelta, timezone
from influxdb import InfluxDBClient
from health_schema import FIELD_TYPES

MEASUREMENTS = frozenset(FIELD_TYPES) - {"GPS", "Device Metadata", "DeviceBatteryLevel"}
INTRADAY = {"HeartRate_Intraday", "Steps_Intraday", "SPO2_Intraday"}
MAX_ROWS = 20000

class DataUnavailable(Exception):
    pass


def literal(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


class InfluxService:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or InfluxDBClient(
            host=settings.influx_host, port=settings.influx_port,
            username=settings.influx_username, password=settings.influx_password,
            database=settings.influx_database, timeout=10, retries=0)

    def close(self):
        self.client.close()

    def query(self, measurement, start, end):
        if measurement not in MEASUREMENTS:
            raise ValueError("Unsupported measurement")
        if start.tzinfo is None or end.tzinfo is None or not timedelta(0) < end - start <= timedelta(days=190):
            raise ValueError("Invalid query interval")
        cfg = self.settings
        where = " AND ".join(f'"{key}" = {literal(value)}' for key, value in (
            ("UserId", cfg.user_id), ("Provider", cfg.provider), ("DeviceId", cfg.device_id)))
        where += f" AND time >= {literal(start.astimezone(timezone.utc).isoformat())} AND time < {literal(end.astimezone(timezone.utc).isoformat())}"
        if measurement in INTRADAY:
            # Hourly aggregates preserve sample counts for weighted daily averages.
            fields = 'SUM("value") AS "sum", COUNT("value") AS "count", MIN("value") AS "min", MAX("value") AS "max"'
            suffix = ' GROUP BY time(1h) fill(none)'
        else:
            names = list(FIELD_TYPES[measurement])
            if measurement == "Activity Records":
                names.append("ActivityName")
            if measurement in {"Sleep Summary", "Sleep Levels"}:
                names.append("isMainSleep")
            fields = ", ".join(f'"{name}"' for name in names)
            suffix = ""
        sql = f'SELECT {fields} FROM "{measurement}" WHERE {where}{suffix} ORDER BY time ASC LIMIT {MAX_ROWS + 1}'
        try:
            rows = list(self.client.query(sql).get_points())
        except Exception:
            raise DataUnavailable("Health data could not be retrieved.") from None
        if len(rows) > MAX_ROWS:
            raise DataUnavailable("Requested data exceeds the safe query limit; use a shorter period.")
        return rows

    def fetch(self, measurements, start, end):
        return {name: self.query(name, start, end) for name in sorted(set(measurements))}
