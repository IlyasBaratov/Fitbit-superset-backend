"""Google Health fetch orchestration with pure metric mappers."""
from datetime import datetime, timedelta, timezone
import logging
import requests
from app.core.exceptions import ProviderError
from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields
from app.providers.http import log_metric_http_error
from app.providers.google_health import vitals, body, sleep, activity, intraday, spo2, workouts

logger = logging.getLogger(__name__)
INTRADAY = (("heart", "HeartRate_Intraday", "1sec"), ("steps", "Steps_Intraday", "1min"))

class GoogleHealthProvider:
    def __init__(self, settings, client, timezone, device_name=None):
        self.settings, self.client, self.timezone = settings, client, timezone
        self.device_name = device_name or settings.devicename
        self.client.timezone = timezone
        self._metadata = {}

    def _available(self, name, call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except requests.HTTPError as error:
            log_metric_http_error(name, error)
            return None
        except ProviderError:
            logger.warning("%s unavailable after provider retries", name)
            return None

    def _range(self, kind, start, end):
        return self._available(kind, self.client.get_google_datapoints_for_date_range, kind, start, end) or []

    def fetch_intraday(self, date, measurements=INTRADAY):
        data = {kind: self._available(kind, self.client.get_google_datapoints_for_date, kind, date) or [] for kind in ("heart-rate", "steps")}
        return intraday.map_intraday(data, date, measurements, self.device_name, self.timezone)

    def fetch_daily_group(self, group, start, end):
        if group == "30d":
            return self._vitals(start, end)
        if group == "100d":
            return sleep.map_sleep({"sleep": self._range("sleep", start, end)}, start, end, self.device_name, self.timezone)
        if group == "365d":
            return self._activity(start, end)
        if group == "none":
            return spo2.map_spo2({"daily-oxygen-saturation": self._range("daily-oxygen-saturation", start, end)}, start, end, self.device_name, self.timezone)
        raise ValueError("Unknown daily metric group")

    def _vitals(self, start, end):
        records = []
        for kind, mapper in (("daily-heart-rate-variability", vitals.map_hrv), ("daily-respiratory-rate", vitals.map_breathing), ("daily-sleep-temperature-derivations", vitals.map_temperature), ("oxygen-saturation", vitals.map_oxygen)):
            records.extend(mapper({kind: self._range(kind, start, end)}, start, end, self.device_name, self.timezone))
        height = self._available("height", self.client.request_google_data_points_list, "height", params={"pageSize": 100}) or {}
        records.extend(body.map_body({"height": height, "weight": self._range("weight", start, end)}, start, end, self.device_name, self.timezone))
        return records

    def _activity(self, start, end):
        records = activity.map_resting({"daily-resting-heart-rate": self._range("daily-resting-heart-rate", start, end)}, start, end, self.device_name, self.timezone)
        for kinds, mapper in ((["active-zone-minutes"], activity.map_zones), (["steps", "total-calories"], activity.map_daily_totals), (["distance"], activity.map_distance), (["sedentary-period"], activity.map_sedentary)):
            data = {}
            for kind in kinds:
                data[kind] = {}
                day = datetime.strptime(start, "%Y-%m-%d")
                last = datetime.strptime(end, "%Y-%m-%d")
                while day <= last:
                    date = {"year": day.year, "month": day.month, "day": day.day}
                    payload = {"range": {"start": {"date": date, "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0}}, "end": {"date": date, "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0}}}, "windowSizeDays": 1}
                    data[kind][day.strftime("%Y-%m-%d")] = self._available(kind, self.client.request_google_data_points_daily_rollup, kind, payload) or {}
                    day += timedelta(days=1)
            records.extend(mapper(data, start, end, self.device_name, self.timezone))
        return records

    def fetch_workouts(self, end=None):
        data = self._available("exercise", self.client.request_google_data_points_list, "exercise", params={"pageSize": 100}) or {}
        return workouts.map_workouts({"exercise": data}, self.device_name, self.timezone)

    def fetch_battery(self):
        logger.debug("Google does not expose Fitbit battery telemetry")
        return []

    def fetch_device_metadata(self):
        self._metadata = self.client.discover_google_device_metadata() or self._metadata
        if not self._metadata:
            return []
        fields = sanitize_fields({"deviceName": self._metadata.get("deviceName"), "deviceModel": self._metadata.get("deviceModel"), "timezone": self.timezone.zone, "firmwareVersion": self._metadata.get("firmwareVersion"), "connectionStatus": self._metadata.get("connectionStatus")})
        return [HealthPoint("Device Metadata", self._metadata.get("_observationTime") or datetime.now(timezone.utc).isoformat(), fields)]

    def refresh_credentials(self):
        return self.client.transport.token_manager.refresh()

    def close(self):
        try:
            self.client.transport.close()
        finally:
            self.client.transport.token_manager.close()
