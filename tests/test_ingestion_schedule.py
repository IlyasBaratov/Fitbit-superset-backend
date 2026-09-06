from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytz
import pytest
from app.core.exceptions import ConfigurationError
from app.ingestion.date_ranges import iter_days, iter_windows
from app.ingestion.jobs import IngestionJobs
from app.ingestion.scheduler import IngestionScheduler


def test_inclusive_bulk_windows_and_boundaries():
    assert list(iter_windows("2026-01-01", "2026-01-29", 28)) == [("2026-01-01", "2026-01-29"), ("2026-01-29", "2026-01-29")]
    assert list(iter_days("2024-02-28", "2024-03-01")) == ["2024-02-28", "2024-02-29", "2024-03-01"]
    for start, end in ((None, "2026-01-01"), ("2026-02-02", "2026-01-01")):
        with pytest.raises(ConfigurationError):
            list(iter_windows(start, end, 28))


def test_schedule_cadence_and_no_duplicates():
    settings = SimpleNamespace(schedule_auto_update=True, auto_update_date_range=1)
    jobs = IngestionJobs(Mock(), settings, pytz.utc)
    runner = IngestionScheduler(jobs, settings)
    runner.register()
    runner.register()
    assert len(runner.scheduler.jobs) == 10
    cadence = [(j.interval, j.unit) for j in runner.scheduler.jobs]
    assert cadence.count((1, "hours")) == 3
    assert cadence.count((20, "minutes")) == 2
    assert cadence.count((6, "hours")) == 2
    assert (3, "minutes") in cadence


def test_jobs_recompute_dates_across_midnight():
    now = [datetime(2026, 8, 21, 6, 59, tzinfo=timezone.utc)]
    ingestion = Mock()
    jobs = IngestionJobs(ingestion, SimpleNamespace(auto_update_date_range=1), pytz.timezone("America/Los_Angeles"), lambda: now[0])
    jobs.sync_intraday()
    ingestion.sync_intraday.assert_called_with("2026-08-20")
    now[0] = datetime(2026, 8, 21, 7, 1, tzinfo=timezone.utc)
    jobs.sync_intraday()
    ingestion.sync_intraday.assert_called_with("2026-08-21")
    jobs.sync_previous_day()
    ingestion.sync_intraday.assert_called_with("2026-08-20")
