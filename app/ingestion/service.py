"""Provider-independent fetch and storage orchestration."""

from app.providers.base import HealthProvider
from app.storage.base import HealthRepository
from app.ingestion.metadata import DeviceMetadataState


class IngestionService:
    def __init__(
        self,
        provider: HealthProvider,
        repository: HealthRepository,
        metadata: DeviceMetadataState,
    ):
        self.provider, self.repository, self.metadata = provider, repository, metadata

    def sync_intraday(self, date: str) -> bool:
        return self.repository.write(self.provider.fetch_intraday(date))

    def sync_daily_group(self, group: str, start: str, end: str) -> bool:
        return self.repository.write(self.provider.fetch_daily_group(group, start, end))

    def sync_workouts(self, end: str | None = None) -> bool:
        return self.repository.write(self.provider.fetch_workouts(end))

    def sync_battery(self) -> bool:
        return self.repository.write(self.provider.fetch_battery())

    def sync_device_metadata(self) -> None:
        for point in self.provider.fetch_device_metadata():
            signature = self.metadata.signature(point)
            if not self.metadata.unchanged(signature) and self.repository.write(
                [point]
            ):
                self.metadata.acknowledge(signature)

    def refresh_credentials(self) -> str:
        return self.provider.refresh_credentials()
