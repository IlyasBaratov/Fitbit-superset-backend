"""High-level collection jobs and provider-window scheduling policy."""

from datetime import datetime, timedelta
from app.ingestion.date_ranges import iter_days, iter_windows, validate_range


class IngestionJobs:
    def __init__(self, ingestion, settings, timezone, clock=None):
        self.ingestion, self.settings, self.timezone = ingestion, settings, timezone
        self.clock = clock or (lambda: datetime.now(timezone))

    def dates(self):
        end = self.clock().astimezone(self.timezone).date()
        return (
            end - timedelta(days=self.settings.auto_update_date_range)
        ).isoformat(), end.isoformat()

    def sync_intraday(self):
        return self.ingestion.sync_intraday(self.dates()[1])

    def sync_previous_day(self):
        previous = self.clock().astimezone(self.timezone).date() - timedelta(days=1)
        return self.ingestion.sync_intraday(previous.isoformat())

    def sync_daily_metrics(self, group):
        return self.ingestion.sync_daily_group(group, *self.dates())

    def sync_workouts(self):
        return self.ingestion.sync_workouts(self.dates()[1])

    def initial_sync(self):
        start, end = self.dates()
        for day in iter_days(start, end):
            self.ingestion.sync_intraday(day)
        for group in ("30d", "100d", "365d", "none"):
            self.ingestion.sync_daily_group(group, start, end)
        self.ingestion.sync_battery()
        self.ingestion.sync_device_metadata()
        self.ingestion.sync_workouts(end)

    def bulk_sync(self, run_pending=lambda: None):
        start, end = self.settings.manual_start_date, self.settings.manual_end_date
        validate_range(start, end)
        self.ingestion.sync_device_metadata()
        self.ingestion.sync_workouts(end)
        self.ingestion.sync_daily_group("none", start, end)
        run_pending()
        for group, gap in (("365d", 360), ("100d", 98), ("30d", 28)):
            for first, last in iter_windows(start, end, gap):
                self.ingestion.sync_daily_group(group, first, last)
                run_pending()
        for day in iter_days(start, end):
            self.ingestion.sync_intraday(day)
            run_pending()
