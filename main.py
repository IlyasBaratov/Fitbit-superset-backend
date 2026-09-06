from app.ingestion.jobs import IngestionJobs
from app.ingestion.scheduler import IngestionScheduler
"""Collector compatibility runner; runtime dependencies are constructed explicitly."""
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
        jobs = IngestionJobs(ingestion, cfg, provider.timezone)
        IngestionScheduler(jobs, cfg).run()
    finally:
        if repository is not None:
            repository.close()
        provider.client.transport.close()
        provider.client.transport.token_manager.close()


if __name__ == "__main__":
    main()
