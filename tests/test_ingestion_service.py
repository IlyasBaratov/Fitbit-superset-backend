from unittest.mock import Mock
import pytest
from app.domain.models import HealthPoint
from app.ingestion.metadata import DeviceMetadataState
from app.ingestion.service import IngestionService
from app.core.exceptions import StorageError


def test_fetch_write_and_metadata_acknowledgement(tmp_path):
    provider, repository = Mock(), Mock()
    metadata = DeviceMetadataState(tmp_path / "state.json", {"UserId": "u"})
    service = IngestionService(provider, repository, metadata)
    point = HealthPoint("Device Metadata", "2026-08-20", {"deviceName": "Watch"})
    provider.fetch_intraday.return_value = [point]
    service.sync_intraday("2026-08-20")
    repository.write.assert_called_once_with([point])
    provider.fetch_device_metadata.return_value = [point]
    repository.write.return_value = False
    service.sync_device_metadata()
    assert not metadata.path.exists()
    repository.write.side_effect = StorageError("failed")
    with pytest.raises(StorageError):
        service.sync_device_metadata()
    assert not metadata.path.exists()
    repository.write.side_effect = None
    repository.write.return_value = True
    service.sync_device_metadata()
    assert metadata.unchanged(metadata.signature(point))
    repository.reset_mock()
    service.sync_device_metadata()
    repository.write.assert_not_called()


def test_ingestion_instances_do_not_share_records(tmp_path):
    first, second = Mock(), Mock()
    one, two = Mock(), Mock()
    state = DeviceMetadataState(tmp_path / "state", {})
    first.fetch_workouts.return_value = [HealthPoint("Activity Records", "2026-08-20", {"ActivityId": "1"})]
    second.fetch_workouts.return_value = []
    IngestionService(first, one, state).sync_workouts()
    IngestionService(second, two, state).sync_workouts()
    two.write.assert_called_once_with([])
    assert len(one.write.call_args.args[0]) == 1
