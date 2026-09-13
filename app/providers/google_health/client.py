"""Google Health URLs, filtering, pagination, rollups and discovery."""

from datetime import datetime, timedelta
import json
import logging
import pytz
import requests
from app.providers.google_health.parsing import (
    parse_google_datapoint_timestamp,
    get_google_datapoint_date_string,
)

logger = logging.getLogger(__name__)


class GoogleHealthClient:
    def __init__(self, settings, transport, timezone=pytz.utc):
        self.settings, self.transport, self.timezone = settings, transport, timezone

    def get_timezone_name(self):
        data = self.transport.request(
            self.get_google_health_api_url("users/me/settings")
        )
        if isinstance(data, dict):
            for source in (data, data.get("settings") or {}):
                for key in ("timezone", "timeZone", "time_zone"):
                    if source.get(key):
                        return source[key]
        logger.warning("Google timezone unavailable; using UTC")
        return "UTC"

    def get_google_health_api_url(self, path):
        return f"{self.settings.google_health_base_url}/{self.settings.google_health_api_version}/{path.lstrip('/')}"

    def request_google_data_points_list(
        self, data_type, params=None, suppress_http_error_log=False
    ):
        endpoint = self.get_google_health_api_url(
            f"users/me/dataTypes/{data_type}/dataPoints"
        )
        return self.transport.request(
            endpoint,
            params=params or {},
            suppress_http_error_log=suppress_http_error_log,
        )

    def request_google_data_points_daily_rollup(self, data_type, payload):
        endpoint = self.get_google_health_api_url(
            f"users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
        )
        headers = {"Accept": "application/json"}
        headers["Content-Type"] = "application/json"
        return self.transport.request(
            endpoint, headers=headers, data=json.dumps(payload), request_type="post"
        )

    def request_google_data_points_rollup(self, data_type, payload):
        endpoint = self.get_google_health_api_url(
            f"users/me/dataTypes/{data_type}/dataPoints:rollUp"
        )
        headers = {"Accept": "application/json"}
        headers["Content-Type"] = "application/json"
        return self.transport.request(
            endpoint, headers=headers, data=json.dumps(payload), request_type="post"
        )

    def get_google_datapoints_for_date(self, data_type, date_str, page_size=10000):
        start_dt_local = self.timezone.localize(datetime.strptime(date_str, "%Y-%m-%d"))
        end_dt_local = self.timezone.localize(
            datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        )
        start_iso = (
            start_dt_local.astimezone(pytz.utc).isoformat().replace("+00:00", "Z")
        )
        end_iso = end_dt_local.astimezone(pytz.utc).isoformat().replace("+00:00", "Z")

        filter_data_type = data_type.replace("-", "_")
        next_date_str = (
            datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        # Data types do not expose a uniform set of filter members.
        if data_type in ["steps"]:
            filters_to_try = [
                f'{filter_data_type}.interval.start_time >= "{start_iso}" AND {filter_data_type}.interval.start_time < "{end_iso}"',
                f'{filter_data_type}.interval.civil_start_time >= "{date_str}T00:00:00" AND {filter_data_type}.interval.civil_start_time < "{next_date_str}T00:00:00"',
            ]
        elif data_type in ["heart-rate", "oxygen-saturation", "weight"]:
            filters_to_try = [
                f'{filter_data_type}.sample_time.physical_time >= "{start_iso}" AND {filter_data_type}.sample_time.physical_time < "{end_iso}"',
            ]
        elif data_type in ["exercise", "sleep"]:
            filters_to_try = [
                f'{filter_data_type}.interval.civil_start_time >= "{date_str}T00:00:00" AND {filter_data_type}.interval.civil_start_time < "{next_date_str}T00:00:00"',
                f'{filter_data_type}.interval.civil_end_time >= "{date_str}T00:00:00" AND {filter_data_type}.interval.civil_end_time < "{next_date_str}T00:00:00"',
            ]
        else:
            # Daily and unsupported data types often reject member-based filters.
            filters_to_try = []

        # Google caps responses at ~5000 points per page regardless of pageSize, so we must
        # follow nextPageToken to avoid silently dropping data (e.g. HR samples earlier in the day).
        def _paginate(extra_params):
            all_points = []
            page_token = None
            first = True
            for _ in range(50):  # safety cap; one day of HR is ~17k samples → ~4 pages
                params = dict(extra_params)
                params["pageSize"] = page_size
                if page_token:
                    params["pageToken"] = page_token
                try:
                    resp = self.request_google_data_points_list(
                        data_type, params=params, suppress_http_error_log=first
                    )
                except requests.exceptions.HTTPError:
                    if first:
                        raise
                    logger.warning(
                        "Pagination interrupted for %s; keeping %d points",
                        data_type,
                        len(all_points),
                    )
                    break
                first = False
                if not isinstance(resp, dict):
                    break
                all_points.extend(resp.get("dataPoints", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            return all_points

        points = None
        used_server_filter = False
        for filter_expr in filters_to_try:
            try:
                points = _paginate({"filter": filter_expr})
                used_server_filter = True
                break
            except requests.exceptions.HTTPError as error:
                if error.response is not None and error.response.status_code in (
                    403,
                    404,
                ):
                    raise
                continue

        if points is None:
            try:
                points = _paginate({})
            except requests.exceptions.HTTPError:
                raise
        filtered = []
        for data_point in points:
            ts = parse_google_datapoint_timestamp(data_point, data_type, self.timezone)
            if not ts:
                continue

            data_point_date = get_google_datapoint_date_string(data_point, data_type)
            if used_server_filter:
                filtered.append((data_point, ts))
                continue

            if data_point_date == date_str:
                filtered.append((data_point, ts))
                continue

            if (
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
                .astimezone(self.timezone)
                .strftime("%Y-%m-%d")
                == date_str
            ):
                filtered.append((data_point, ts))
        return filtered

    def get_google_datapoints_for_date_range(
        self, data_type, start_date_str, end_date_str, page_size=10000
    ):
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        aggregated = []
        current = start_date
        while current <= end_date:
            aggregated.extend(
                self.get_google_datapoints_for_date(
                    data_type, current.strftime("%Y-%m-%d"), page_size=page_size
                )
            )
            current += timedelta(days=1)
        return aggregated

    def get_google_session_datapoints_for_date_range(
        self, data_type, start_date_str, end_date_str, page_size=1000
    ):
        """Fetch ECG/IRN sessions once, then enforce the requested local date range."""
        start_local = self.timezone.localize(
            datetime.strptime(start_date_str, "%Y-%m-%d")
        )
        end_local = self.timezone.localize(
            datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
        )
        start_utc = start_local.astimezone(pytz.utc)
        end_utc = end_local.astimezone(pytz.utc)
        base_params = {}
        if data_type == "electrocardiogram":
            start_iso = start_utc.isoformat().replace("+00:00", "Z")
            # Google documents only the inclusive lower bound for ECG sessions.
            base_params["filter"] = (
                f'electrocardiogram.interval.start_time >= "{start_iso}"'
            )

        points = []
        page_token = None
        for page in range(50):
            params = dict(base_params)
            params["pageSize"] = page_size
            if page_token:
                params["pageToken"] = page_token
            try:
                response = self.request_google_data_points_list(
                    data_type, params=params, suppress_http_error_log=page == 0
                )
            except requests.exceptions.HTTPError as error:
                if (
                    page == 0
                    and base_params
                    and error.response is not None
                    and error.response.status_code == 400
                ):
                    base_params = {}
                    continue
                if page:
                    logger.warning(
                        "Pagination interrupted for %s; keeping %d points",
                        data_type,
                        len(points),
                    )
                    break
                raise
            if not isinstance(response, dict):
                break
            points.extend(response.get("dataPoints", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        filtered = []
        for data_point in points:
            timestamp = parse_google_datapoint_timestamp(
                data_point, data_type, self.timezone
            )
            if not timestamp:
                continue
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if start_utc <= observed < end_utc:
                filtered.append((data_point, timestamp))
        return filtered

    def discover_google_device_metadata(self):
        """Return actual device metadata attached to a recent Google data point."""
        for data_type in (
            "heart-rate",
            "steps",
            "daily-resting-heart-rate",
            "weight",
            "exercise",
        ):
            try:
                resp = self.request_google_data_points_list(
                    data_type, params={"pageSize": 1}, suppress_http_error_log=True
                )
            except requests.exceptions.HTTPError:
                continue
            if not isinstance(resp, dict):
                continue
            for dp in resp.get("dataPoints", []):
                device = (dp.get("dataSource") or {}).get("device") or {}
                name = device.get("displayName")
                if name:
                    metadata = {
                        "deviceName": name.strip(),
                        "deviceModel": device.get("model"),
                        "firmwareVersion": device.get("firmwareVersion"),
                        "connectionStatus": device.get("connectionStatus"),
                    }
                    try:
                        metadata["_observationTime"] = parse_google_datapoint_timestamp(
                            dp, data_type, self.timezone
                        )
                    except (TypeError, ValueError):
                        metadata["_observationTime"] = None
                    return metadata
        return {}

    def discover_google_device_name(self):
        return self.discover_google_device_metadata().get("deviceName")
