"""Fitbit fetch orchestration; payload interpretation lives in pure mappers."""
from datetime import datetime, timedelta, timezone
import logging
import xml.etree.ElementTree as ET
import requests
from app.core.exceptions import ProviderError
from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields, utc_timestamp
from app.providers.http import log_metric_http_error
from app.providers.fitbit import mapper, vitals, sleep, activity, tcx

logger = logging.getLogger(__name__)
INTRADAY = (("heart", "HeartRate_Intraday", "1sec"), ("steps", "Steps_Intraday", "1min"))

class FitbitProvider:
    def __init__(self, settings, client, timezone, device_name=None):
        self.settings, self.client, self.timezone = settings, client, timezone
        self.device_name = device_name or settings.devicename

    def _available(self, name, call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except requests.HTTPError as error:
            log_metric_http_error(name, error)
            return None
        except ProviderError:
            logger.warning("%s unavailable after provider retries", name)
            return None

    def fetch_intraday(self, date, measurements=INTRADAY):
        payloads = {}
        for kind, _, resolution in measurements:
            payloads["intraday:" + kind] = self._available(kind, self.client.intraday, kind, date, resolution) or {"activities-" + kind + "-intraday": {"dataset": []}}
        return mapper.map_intraday(payloads, date, measurements, self.device_name, self.timezone)

    def fetch_daily_group(self, group, start, end):
        if group == "30d":
            points = []
            for method, mapping in (("hrv", vitals.map_hrv), ("breathing", vitals.map_breathing), ("skin_temperature", vitals.map_temperature), ("spo2_intraday", vitals.map_oxygen), ("weight", vitals.map_body)):
                result = self._available(method, getattr(self.client, method), start, end)
                points.extend(mapping({method: result or ([] if method == "spo2_intraday" else {})}, start, end, self.device_name, self.timezone))
            return points
        if group == "100d":
            result = self._available("sleep", self.client.sleep, start, end) or {}
            return sleep.map_sleep({"sleep": result}, start, end, self.device_name, self.timezone)
        if group == "365d":
            payloads = {}
            for kind in ("minutesSedentary", "minutesLightlyActive", "minutesFairlyActive", "minutesVeryActive", "steps", "calories", "distance"):
                payloads["activity_series:" + kind] = self._available(kind, self.client.activity_series, kind, start, end) or {}
            for method in ("heart_summary", "active_zone_minutes"):
                payloads[method] = self._available(method, getattr(self.client, method), start, end) or {}
            return activity.map_activity(payloads, start, end, self.device_name, self.timezone)
        if group == "none":
            result = self._available("spo2", self.client.spo2, start, end) or []
            return mapper.map_spo2({"spo2": result}, start, end, self.device_name, self.timezone)
        raise ValueError("Unknown daily metric group")

    def fetch_workouts(self, end=None):
        end = end or datetime.now(self.timezone).strftime("%Y-%m-%d")
        before = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        data = self._available("activities", self.client.activities, params={"beforeDate": before, "sort": "desc", "limit": 50, "offset": 0}) or {"activities": []}
        points = mapper.map_workouts({"activities": data}, end, self.device_name, self.timezone)
        count = 0
        for record in data.get("activities", []):
            if record.get("hasGps") and record.get("tcxLink") and count <= 10:
                count += 1
                response = self._available("TCX", self.client.tcx, record["tcxLink"], headers={"Accept": "application/x-www-form-urlencoded"}, params={"includePartialTCX": "false"})
                if response is None:
                    continue
                name = record.get("activityName", "Unknown-Activity")
                activity_id = str(record["logId"]) if record.get("logId") is not None else utc_timestamp(record["startTime"], self.timezone.zone) + "-" + name
                try:
                    points.extend(tcx.map_tcx(response.text, activity_id, name, self.timezone))
                except (ET.ParseError, ValueError, TypeError, KeyError):
                    logger.warning("Skipping malformed Fitbit TCX data")
        return points

    def fetch_battery(self):
        devices = self._available("battery", self.client.devices) or []
        if not devices or devices[0].get("batteryLevel") is None or not devices[0].get("lastSyncTime"):
            return []
        return [HealthPoint("DeviceBatteryLevel", utc_timestamp(devices[0]["lastSyncTime"], self.timezone.zone), {"value": float(devices[0]["batteryLevel"])})]

    def fetch_device_metadata(self):
        devices = self._available("metadata", self.client.devices) or []
        if not devices:
            return []
        device = devices[0]
        fields = sanitize_fields({"deviceName": device.get("deviceVersion") or self.device_name, "deviceModel": device.get("deviceVersion"), "timezone": self.timezone.zone, "lastSyncTime": device.get("lastSyncTime"), "batteryPercent": device.get("batteryLevel"), "firmwareVersion": device.get("firmwareVersion"), "connectionStatus": device.get("connectionStatus")})
        return [HealthPoint("Device Metadata", device.get("lastSyncTime") or datetime.now(timezone.utc).isoformat(), fields)]

    def refresh_credentials(self):
        return self.client.transport.token_manager.refresh()
