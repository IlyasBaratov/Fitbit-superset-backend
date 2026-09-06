"""Persistent provider HTTP sessions with bounded retry behavior."""
import logging
import time
import requests
from app.core.exceptions import ProviderError

logger = logging.getLogger(__name__)


def retry_after_seconds(response):
    for header, padding in (("Retry-After", 0), ("Fitbit-Rate-Limit-Reset", 300)):
        try:
            if response.headers.get(header):
                return max(0, int(response.headers[header])) + padding
        except ValueError:
            pass
    return 120


def log_metric_http_error(metric_name, error):
    status = error.response.status_code if error.response is not None else None
    if status in (403, 404):
        logger.warning("%s unavailable: permission or device capability (HTTP %s)", metric_name, status)
    else:
        logger.error("%s failed (HTTP %s)", metric_name, status)


class ProviderHTTPClient:
    def __init__(self, settings, token_manager, session=None, sleep=time.sleep):
        self.settings, self.token_manager = settings, token_manager
        self.session = session or requests.Session()
        self._owns_session = session is None
        self.sleep = sleep

    def request(self, url, headers=None, params=None, data=None, request_type="get", suppress_http_error_log=False):
        cfg = self.settings
        if request_type not in {"get", "post"}:
            raise ValueError("Only GET and POST provider requests are supported")
        if cfg.health_api_provider == "google" and url.startswith(cfg.fitbit_api_base_url):
            raise ProviderError("A Fitbit endpoint cannot be used by Google Health")
        headers = dict(headers or {})
        headers.setdefault("Accept", "application/json")
        if cfg.health_api_provider == "fitbit":
            headers.setdefault("Accept-Language", cfg.fitbit_language)
        for attempt in range(cfg.request_max_retries + 1):
            headers["Authorization"] = "Bearer " + self.token_manager.get_access_token()
            try:
                response = self.session.request(request_type, url, headers=headers, params=params or {}, data=data or {}, timeout=cfg.request_timeout_seconds)
                status = response.status_code
                if status == 200:
                    return response if url.endswith(".tcx") else response.json()
                if status == 429:
                    if attempt >= cfg.request_max_retries:
                        response.raise_for_status()
                    self.sleep(min(retry_after_seconds(response), 300))
                elif status == 401:
                    if attempt >= min(cfg.expired_token_max_retry, cfg.request_max_retries):
                        response.raise_for_status()
                    self.token_manager.refresh()
                elif status in {500, 502, 503, 504}:
                    if attempt >= min(cfg.server_error_max_retry, cfg.request_max_retries):
                        if cfg.skip_request_on_server_error:
                            logger.warning("Skipping metric after repeated provider server failures (HTTP %s)", status)
                            return None
                        response.raise_for_status()
                    self.sleep(min(30 * (attempt + 1), 120))
                else:
                    if not suppress_http_error_log:
                        logger.warning("Provider request failed (HTTP %s)", status)
                    response.raise_for_status()
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= cfg.request_max_retries:
                    raise ProviderError("Provider network retry budget exhausted") from None
                self.sleep(min(5 * (attempt + 1), 30))
        raise ProviderError("Provider request retry budget exhausted")

    def close(self):
        if self._owns_session:
            self.session.close()
