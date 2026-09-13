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


def test_calendar_points_go_only_to_the_calendar_repository(tmp_path):
    provider, repository, calendar, calendar_repository = Mock(), Mock(), Mock(), Mock()
    state = DeviceMetadataState(tmp_path / "state.json", {})
    point = HealthPoint("Calendar Events", "2026-09-01T09:00:00+00:00", {"summary": "Standup"})
    calendar.fetch_events.return_value = [point]
    calendar_repository.write.return_value = True
    service = IngestionService(provider, repository, state, calendar, calendar_repository)

    assert service.sync_calendar("2026-08-25", "2026-09-02") is True
    calendar.fetch_events.assert_called_once_with("2026-08-25", "2026-09-02")
    calendar_repository.write.assert_called_once_with([point])
    repository.write.assert_not_called()


def test_calendar_sync_without_a_calendar_provider_is_a_no_op(tmp_path):
    repository = Mock()
    state = DeviceMetadataState(tmp_path / "state.json", {})

    assert IngestionService(Mock(), repository, state).sync_calendar("2026-09-01", "2026-09-02") is False
    assert IngestionService(Mock(), repository, state, Mock()).sync_calendar("2026-09-01", "2026-09-02") is False
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
