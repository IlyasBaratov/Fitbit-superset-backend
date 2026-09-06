"""Influx writes and historical field compatibility, owned by one instance."""
from copy import deepcopy
import logging
from app.core.exceptions import StorageError
from app.domain.measurements import FIELD_TYPES
from app.domain.models import HealthPoint
from app.storage.influx.schema import prepare_points

logger = logging.getLogger(__name__)

class InfluxHealthRepository:
    def __init__(self, settings, common_tags, timezone, client=None):
        self.settings, self.common_tags, self.timezone = settings, dict(common_tags), timezone
        self.field_types = deepcopy(FIELD_TYPES)
        self.client, self.write_api = client, None
        if settings.dry_run_mode:
            return
        if self.client is None:
            self.client = self._create_client()
        if settings.influxdb_version == "2":
            from influxdb_client.client.write_api import SYNCHRONOUS
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        if settings.influxdb_version == "1":
            self._detect_field_types()

    def _create_client(self):
        cfg = self.settings
        if cfg.influxdb_version == "1":
            from influxdb import InfluxDBClient
            return InfluxDBClient(host=cfg.influxdb_host, port=cfg.influxdb_port, username=cfg.influxdb_username, password=cfg.influxdb_password, database=cfg.influxdb_database)
        if cfg.influxdb_version == "2":
            from influxdb_client import InfluxDBClient
            return InfluxDBClient(url=cfg.influxdb_url, token=cfg.influxdb_token, org=cfg.influxdb_org)
        from influxdb_client_3 import InfluxDBClient3
        return InfluxDBClient3(host=f"http://{cfg.influxdb_host}:{cfg.influxdb_port}", token=cfg.influxdb_v3_access_token, database=cfg.influxdb_database)

    def _detect_field_types(self):
        for measurement in ("RestingHR", "Total Steps"):
            try:
                rows = self.client.query(f'SHOW FIELD KEYS FROM "{measurement}"').get_points(measurement=measurement)
                value = next((row for row in rows if row.get("fieldKey") == "value"), None)
            except Exception:
                logger.warning("Could not inspect field types for %s", measurement)
                continue
            if value and value.get("fieldType") in {"float", "integer"}:
                self.field_types[measurement]["value"] = float if value["fieldType"] == "float" else int

    def write(self, points: list[HealthPoint]) -> bool:
        """Return true only after a nonempty batch is acknowledged by storage."""
        records = [point.as_record() for point in points]
        prepared = prepare_points(records, self.common_tags, self.timezone, self.field_types)
        if len(prepared) != len(records):
            logger.warning("Skipped %d invalid points", len(records) - len(prepared))
        if not prepared or self.settings.dry_run_mode:
            logger.info("No write: %d validated points, dry_run=%s", len(prepared), self.settings.dry_run_mode)
            return False
        try:
            if self.settings.influxdb_version == "1":
                if self.client.write_points(prepared) is False:
                    raise StorageError("InfluxDB did not acknowledge the write")
            elif self.settings.influxdb_version == "2":
                self.write_api.write(bucket=self.settings.influxdb_bucket, org=self.settings.influxdb_org, record=prepared)
            else:
                self.client.write(record=prepared)
        except Exception:
            raise StorageError("Health data could not be written to InfluxDB") from None
        logger.info("Successfully wrote %d points to InfluxDB", len(prepared))
        return True

    def close(self):
        try:
            if self.write_api is not None:
                self.write_api.close()
        finally:
            if self.client is not None:
                self.client.close()
