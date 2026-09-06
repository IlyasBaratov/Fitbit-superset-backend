"""Synchronous jobs avoid overlapping collector runs."""

import logging
import threading
import requests
import schedule
from app.core.exceptions import StorageError, ProviderError

logger = logging.getLogger(__name__)


class IngestionScheduler:
    def __init__(self, jobs, settings, scheduler=None, stop_event=None):
        self.jobs, self.settings = jobs, settings
        self.scheduler = scheduler or schedule.Scheduler()
        self.stop_event = stop_event or threading.Event()
        self._registered = False

    def _run_job(self, callback, *args):
        try:
            return callback(*args)
        except (StorageError, ProviderError, requests.RequestException):
            logger.error(
                "Ingestion job %s failed; it will be retried at its next scheduled run",
                callback.__name__,
            )

    def register(self):
        if self._registered:
            return
        self._registered = True
        jobs, ingestion = self.jobs, self.jobs.ingestion
        self.scheduler.every(1).hours.do(self._run_job, ingestion.refresh_credentials)
        if not self.settings.schedule_auto_update:
            return
        self.scheduler.every(3).minutes.do(self._run_job, jobs.sync_intraday)
        self.scheduler.every(1).hours.do(self._run_job, jobs.sync_previous_day)
        self.scheduler.every(20).minutes.do(self._run_job, ingestion.sync_battery)
        self.scheduler.every(20).minutes.do(
            self._run_job, ingestion.sync_device_metadata
        )
        for group, hours in (("30d", 3), ("100d", 4), ("365d", 6), ("none", 6)):
            self.scheduler.every(hours).hours.do(
                self._run_job, jobs.sync_daily_metrics, group
            )
        self.scheduler.every(1).hours.do(self._run_job, jobs.sync_workouts)

    def run(self):
        # Automatic mode refresh begins after startup; bulk runs refresh between chunks.
        if self.settings.auto_date_range:
            self.jobs.initial_sync()
            self.register()
        else:
            self.register()
            self.jobs.bulk_sync(self.scheduler.run_pending)
        if self.settings.schedule_auto_update:
            while not self.stop_event.is_set():
                self.scheduler.run_pending()
                self.stop_event.wait(30)
