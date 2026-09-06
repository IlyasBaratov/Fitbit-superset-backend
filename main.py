"""Collector compatibility runner; runtime dependencies are constructed explicitly."""
from datetime import datetime, timedelta
import time
import schedule
from app.core.config import WorkerSettings
from app.core.logging import configure_logging
from app.core.exceptions import ConfigurationError
from app.domain.normalization import build_common_tags
from app.providers.factory import create_provider
from app.storage.influx.repository import InfluxHealthRepository
from app.ingestion.service import IngestionService
from app.ingestion.metadata import DeviceMetadataState


def main():
    cfg = WorkerSettings.from_env()
    configure_logging(cfg.log_level, cfg.fitbit_log_file_path, (cfg.client_secret, cfg.google_client_secret, cfg.influxdb_password, cfg.influxdb_token, cfg.influxdb_v3_access_token))
    provider = create_provider(cfg)
    repository = None
    try:
        tags = build_common_tags(cfg.user_id, cfg.health_api_provider, provider.device_name, cfg.device_id)
        repository = InfluxHealthRepository(cfg, tags, provider.timezone.zone)
        ingestion = IngestionService(provider, repository, DeviceMetadataState(cfg.device_metadata_state_path, tags))
        scheduler = schedule.Scheduler()
        def dates():
            end = datetime.now(provider.timezone)
            start = end - timedelta(days=cfg.auto_update_date_range)
            return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        start, end = dates() if cfg.auto_date_range else (cfg.manual_start_date, cfg.manual_end_date)
        if not start or not end:
            raise ConfigurationError("Manual import requires MANUAL_START_DATE and MANUAL_END_DATE")
        days = [(datetime.strptime(start, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1)]
        if not days:
            raise ConfigurationError("Manual import end must not precede start")
        if cfg.auto_date_range:
            for day in days:
                ingestion.sync_intraday(day)
            for group in ("30d", "100d", "365d", "none"):
                ingestion.sync_daily_group(group, start, end)
            ingestion.sync_battery()
            ingestion.sync_device_metadata()
            ingestion.sync_workouts(end)
        else:
            scheduler.every(1).hours.do(ingestion.refresh_credentials)
            ingestion.sync_device_metadata()
            ingestion.sync_workouts(end)
            ingestion.sync_daily_group("none", start, end)
            for group, gap in (("365d", 360), ("100d", 98), ("30d", 28)):
                for index in range(0, len(days), gap):
                    ingestion.sync_daily_group(group, days[index], days[min(index + gap, len(days)-1)])
                    scheduler.run_pending()
            for day in days:
                ingestion.sync_intraday(day)
                scheduler.run_pending()
        if cfg.schedule_auto_update:
            scheduler.every(1).hours.do(ingestion.refresh_credentials)
            scheduler.every(3).minutes.do(lambda: ingestion.sync_intraday(dates()[1]))
            scheduler.every(1).hours.do(lambda: ingestion.sync_intraday((datetime.strptime(dates()[1], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")))
            scheduler.every(20).minutes.do(ingestion.sync_battery)
            scheduler.every(20).minutes.do(ingestion.sync_device_metadata)
            for group, hours in (("30d", 3), ("100d", 4), ("365d", 6), ("none", 6)):
                scheduler.every(hours).hours.do(lambda group=group: ingestion.sync_daily_group(group, *dates()))
            scheduler.every(1).hours.do(lambda: ingestion.sync_workouts(dates()[1]))
            while True:
                scheduler.run_pending()
                time.sleep(30)
    finally:
        if repository is not None:
            repository.close()
        provider.client.transport.close()
        provider.client.transport.token_manager.close()


if __name__ == "__main__":
    main()
