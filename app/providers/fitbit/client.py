"""Fitbit endpoint definitions; callers never construct provider URLs."""
class FitbitClient:
    def __init__(self, settings, transport):
        self.settings, self.transport = settings, transport

    def _get(self, path, **kwargs):
        return self.transport.request(self.settings.fitbit_api_base_url + path, **kwargs)

    def tcx(self, url, **kwargs):
        return self.transport.request(url, **kwargs)

    def get_timezone_name(self):
        return self.profile()["user"]["timezone"]

    def profile(self, **kwargs):
        return self._get(f"/1/user/-/profile.json", **kwargs)

    def devices(self, **kwargs):
        return self._get(f"/1/user/-/devices.json", **kwargs)

    def intraday(self, metric, date_str, resolution, **kwargs):
        return self._get(f"/1/user/-/activities/{metric}/date/{date_str}/1d/{resolution}.json", **kwargs)

    def hrv(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/hrv/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def breathing(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/br/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def skin_temperature(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/temp/skin/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def spo2_intraday(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/spo2/date/{start_date_str}/{end_date_str}/all.json", **kwargs)

    def weight(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/body/log/weight/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def sleep(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1.2/user/-/sleep/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def activity_series(self, activity_type, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/activities/tracker/{activity_type}/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def heart_summary(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/activities/heart/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def active_zone_minutes(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/activities/active-zone-minutes/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def spo2(self, start_date_str, end_date_str, **kwargs):
        return self._get(f"/1/user/-/spo2/date/{start_date_str}/{end_date_str}.json", **kwargs)

    def activities(self, **kwargs):
        return self._get(f"/1/user/-/activities/list.json", **kwargs)

