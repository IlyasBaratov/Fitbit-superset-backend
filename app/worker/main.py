"""Worker composition root. Importing it never starts collection."""

from contextlib import ExitStack
import logging
import signal
import threading
from app.core.config import WorkerSettings
from app.core.exceptions import ConfigurationError, ProviderError, StorageError
from app.core.logging import configure_logging
from app.domain.normalization import build_common_tags
from app.providers.factory import create_provider
from app.storage.influx.repository import InfluxHealthRepository
from app.ingestion.service import IngestionService
from app.ingestion.metadata import DeviceMetadataState
from app.ingestion.jobs import IngestionJobs
from app.ingestion.scheduler import IngestionScheduler
from app.ingestion.date_ranges import validate_range

logger = logging.getLogger(__name__)


def run(settings: WorkerSettings, stop_event=None) -> None:
    """Build a single-user runtime with dependencies owned by this invocation."""
    if not settings.auto_date_range:
        validate_range(settings.manual_start_date, settings.manual_end_date)
    with ExitStack() as resources:
        provider = create_provider(settings)
        resources.callback(provider.close)
        tags = build_common_tags(
            settings.user_id,
            settings.health_api_provider,
            provider.device_name,
            settings.device_id,
        )
        repository = InfluxHealthRepository(settings, tags, provider.timezone.zone)
        resources.callback(repository.close)
        metadata = DeviceMetadataState(settings.device_metadata_state_path, tags)
        ingestion = IngestionService(provider, repository, metadata)
        jobs = IngestionJobs(ingestion, settings, provider.timezone)
        IngestionScheduler(jobs, settings, stop_event=stop_event).run()


def main() -> int:
    stop_event = threading.Event()
    previous_handlers = {}
    try:
        settings = WorkerSettings.from_env()
        configure_logging(
            settings.log_level,
            settings.fitbit_log_file_path,
            secrets=(
                settings.client_secret,
                settings.google_client_secret,
                settings.calendar_client_secret,
                settings.influxdb_password,
                settings.influxdb_token,
                settings.influxdb_v3_access_token,
            ),
            overwrite=settings.overwrite_log_file,
        )
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.signal(
                    signum, lambda *_: stop_event.set()
                )
        run(settings, stop_event)
        return 0
    except (ConfigurationError, ProviderError, StorageError) as error:
        logger.error("Worker stopped: %s", error)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
