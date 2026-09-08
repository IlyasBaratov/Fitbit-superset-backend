from app.core.exceptions import ConfigurationError
from dataclasses import dataclass, field
import os
from dotenv import load_dotenv
import pytz


@dataclass
class Settings:
    api_token: str = field(repr=False)
    gemini_key: str = field(repr=False)
    model: str
    user_id: str = "user_001"
    provider: str = "google"
    device_id: str = "fitbit_air_001"
    timezone: str = "America/Los_Angeles"
    influx_host: str = "localhost"
    influx_port: int = 8086
    influx_database: str = "FitbitHealthStats"
    influx_username: str = ""
    influx_password: str = field(default="", repr=False)
    default_days: int = 7
    max_days: int = 90
    cache_seconds: int = 300
    gemini_timeout_ms: int = 45000
    gemini_retry_attempts: int = 3
    gemini_retry_base_ms: int = 250
    gemini_retry_max_backoff_ms: int = 2000
    gemini_retry_jitter_ms: int = 200
    gemini_retry_max_elapsed_ms: int = 55000
    fallback_model: str = ""
    calendar_client_id: str = ""
    calendar_client_secret: str = field(default="", repr=False)
    calendar_token_file_path: str = "./tokens/google_calendar.token"
    calendar_redirect_uri: str = "http://localhost:8000/api/calendar/callback"
    calendar_ids: tuple[str, ...] = ("primary",)

    def __post_init__(self):
        if len(self.api_token) < 32:
            raise ValueError("AI_API_TOKEN must contain at least 32 characters")
        if not self.gemini_key or not self.model:
            raise ValueError("GEMINI_API_KEY and MODEL_NAME are required")
        if not self.user_id or not self.provider or not self.device_id:
            raise ValueError("User, provider and device configuration are required")
        if not 1 <= self.default_days <= self.max_days <= 90:
            raise ValueError("Analysis days must satisfy 1 <= default <= maximum <= 90")
        if self.gemini_timeout_ms <= 0:
            raise ValueError("GEMINI_TIMEOUT_MS must be positive")
        if self.gemini_retry_attempts < 1:
            raise ValueError("GEMINI_RETRY_ATTEMPTS must be at least 1")
        if (
            min(
                self.gemini_retry_base_ms,
                self.gemini_retry_max_backoff_ms,
                self.gemini_retry_jitter_ms,
            )
            < 0
        ):
            raise ValueError("Gemini retry timing values must be non-negative")
        if self.gemini_retry_max_elapsed_ms <= 0:
            raise ValueError("GEMINI_RETRY_MAX_ELAPSED_MS must be positive")
        pytz.timezone(self.timezone)

    @classmethod
    def from_env(cls):
        load_dotenv()
        zone = os.getenv("LOCAL_TIMEZONE", "Automatic")
        return cls(
            api_token=os.getenv("AI_API_TOKEN", ""),
            gemini_key=os.getenv("GEMINI_API_KEY", ""),
            model=os.getenv("MODEL_NAME") or os.getenv("GEMINI_MODEL", ""),
            user_id=os.getenv("USER_ID", "user_001"),
            provider=os.getenv("HEALTH_API_PROVIDER", "fitbit"),
            device_id=os.getenv("DEVICE_ID", "fitbit_air_001"),
            timezone=os.getenv("TZ", "America/Los_Angeles")
            if zone == "Automatic"
            else zone,
            influx_host=os.getenv("INFLUXDB_HOST", "localhost"),
            influx_port=int(os.getenv("INFLUXDB_PORT", "8086")),
            influx_database=os.getenv("INFLUXDB_DATABASE", "FitbitHealthStats"),
            influx_username=os.getenv("INFLUXDB_USERNAME", ""),
            influx_password=os.getenv("INFLUXDB_PASSWORD", ""),
            default_days=int(os.getenv("AI_DEFAULT_ANALYSIS_DAYS", "7")),
            max_days=int(os.getenv("AI_MAX_ANALYSIS_DAYS", "90")),
            gemini_timeout_ms=int(os.getenv("GEMINI_TIMEOUT_MS", "45000")),
            gemini_retry_attempts=int(os.getenv("GEMINI_RETRY_ATTEMPTS", "3")),
            gemini_retry_base_ms=int(os.getenv("GEMINI_RETRY_BASE_MS", "250")),
            gemini_retry_max_backoff_ms=int(
                os.getenv("GEMINI_RETRY_MAX_BACKOFF_MS", "2000")
            ),
            gemini_retry_jitter_ms=int(os.getenv("GEMINI_RETRY_JITTER_MS", "200")),
            gemini_retry_max_elapsed_ms=int(
                os.getenv("GEMINI_RETRY_MAX_ELAPSED_MS", "55000")
            ),
            fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", ""),
            calendar_client_id=os.getenv("CALENDAR_CLIENT_ID")
            or os.getenv("GOOGLE_CLIENT_ID", ""),
            calendar_client_secret=os.getenv("CALENDAR_CLIENT_SECRET")
            or os.getenv("GOOGLE_CLIENT_SECRET", ""),
            calendar_token_file_path=os.getenv("CALENDAR_TOKEN_FILE_PATH")
            or "./tokens/google_calendar.token",
            calendar_redirect_uri=os.getenv("CALENDAR_REDIRECT_URI")
            or "http://localhost:8000/api/calendar/callback",
            calendar_ids=tuple(
                part.strip()
                for part in os.getenv("CALENDAR_IDS", "").split(",")
                if part.strip()
            )
            or ("primary",),
        )


import logging
from datetime import datetime


@dataclass(frozen=True)
class WorkerSettings:
    """Collector configuration; no API or Gemini credentials are required."""

    fitbit_log_file_path: str
    token_file_path: str
    overwrite_log_file: bool
    fitbit_language: str
    health_api_provider: str
    fitbit_api_base_url: str
    google_health_base_url: str
    google_health_api_version: str
    google_oauth_token_url: str
    influxdb_version: str
    influxdb_host: str
    influxdb_port: int
    influxdb_username: str
    influxdb_password: str = field(repr=False)
    influxdb_database: str
    influxdb_bucket: str
    influxdb_org: str
    influxdb_token: str = field(repr=False)
    influxdb_url: str
    influxdb_v3_access_token: str = field(repr=False)
    client_id: str
    client_secret: str = field(repr=False)
    google_client_id: str
    google_client_secret: str = field(repr=False)
    devicename: str
    user_id: str
    device_id: str
    device_metadata_state_path: str
    manual_start_date: str | None
    manual_end_date: str | None
    auto_date_range: bool
    auto_update_date_range: int
    local_timezone: str
    schedule_auto_update: bool
    server_error_max_retry: int
    expired_token_max_retry: int = field(repr=False)
    skip_request_on_server_error: bool
    request_max_retries: int
    request_timeout_seconds: int
    dry_run_mode: bool
    log_level_name: str
    log_level: int
    calendar_sync_enabled: bool
    calendar_token_file_path: str
    calendar_ids: tuple[str, ...]
    calendar_client_id: str
    calendar_client_secret: str = field(repr=False)
    calendar_sync_days_back: int
    calendar_sync_days_ahead: int
    calendar_api_base_url: str

    @classmethod
    def from_env(cls):
        load_dotenv()
        FITBIT_LOG_FILE_PATH = (
            os.environ.get("FITBIT_LOG_FILE_PATH")
            or "your/expected/log/file/location/path"
        )
        TOKEN_FILE_PATH = (
            os.environ.get("TOKEN_FILE_PATH")
            or "your/expected/token/file/location/path"
        )
        OVERWRITE_LOG_FILE = True
        FITBIT_LANGUAGE = "en_US"
        HEALTH_API_PROVIDER = (
            (os.environ.get("HEALTH_API_PROVIDER") or "fitbit").strip().lower()
        )
        if HEALTH_API_PROVIDER not in {"fitbit", "google"}:
            raise ConfigurationError("HEALTH_API_PROVIDER must be fitbit or google")
        FITBIT_API_BASE_URL = "https://api.fitbit.com"
        GOOGLE_HEALTH_BASE_URL = (
            os.environ.get("GOOGLE_HEALTH_BASE_URL") or "https://health.googleapis.com"
        )
        GOOGLE_HEALTH_API_VERSION = os.environ.get("GOOGLE_HEALTH_API_VERSION") or "v4"
        GOOGLE_OAUTH_TOKEN_URL = (
            os.environ.get("GOOGLE_OAUTH_TOKEN_URL")
            or "https://oauth2.googleapis.com/token"
        )
        INFLUXDB_VERSION = os.environ.get("INFLUXDB_VERSION") or "1"
        if INFLUXDB_VERSION not in {"1", "2", "3"}:
            raise ConfigurationError("INFLUXDB_VERSION must be 1, 2 or 3")
        INFLUXDB_HOST = os.environ.get("INFLUXDB_HOST") or "localhost"
        INFLUXDB_PORT = int(os.environ.get("INFLUXDB_PORT") or "8086")
        INFLUXDB_USERNAME = (
            os.environ.get("INFLUXDB_USERNAME") or "your_influxdb_username"
        )
        INFLUXDB_PASSWORD = (
            os.environ.get("INFLUXDB_PASSWORD") or "your_influxdb_password"
        )
        INFLUXDB_DATABASE = (
            os.environ.get("INFLUXDB_DATABASE") or "your_influxdb_database_name"
        )
        INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET") or "your_bucket_name_here"
        INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG") or "your_org_here"
        INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN") or "your_token_here"
        INFLUXDB_URL = os.environ.get("INFLUXDB_URL") or "http://your_url_here:8086"
        INFLUXDB_V3_ACCESS_TOKEN = os.getenv("INFLUXDB_V3_ACCESS_TOKEN", "")
        client_id = os.environ.get("CLIENT_ID") or "your_application_client_ID"
        client_secret = (
            os.environ.get("CLIENT_SECRET") or "your_application_client_secret"
        )
        google_client_id = os.environ.get("GOOGLE_CLIENT_ID") or client_id
        google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or client_secret
        DEVICENAME = os.environ.get("DEVICENAME") or "Your_Device_Name"
        USER_ID = os.environ.get("USER_ID") or "user_001"
        DEVICE_ID = os.environ.get("DEVICE_ID") or "fitbit_air_001"
        DEVICE_METADATA_STATE_PATH = os.environ.get(
            "DEVICE_METADATA_STATE_PATH"
        ) or os.path.join(
            os.path.dirname(TOKEN_FILE_PATH), "device_metadata_state.json"
        )
        MANUAL_START_DATE = os.getenv("MANUAL_START_DATE", None)
        MANUAL_END_DATE = os.getenv(
            "MANUAL_END_DATE", datetime.today().strftime("%Y-%m-%d")
        )
        AUTO_DATE_RANGE = (
            False
            if os.environ.get("AUTO_DATE_RANGE")
            in ["False", "false", "FALSE", "f", "F", "no", "No", "NO", "0"]
            else (not bool(MANUAL_START_DATE))
        )
        auto_update_date_range = 1
        LOCAL_TIMEZONE = os.environ.get("LOCAL_TIMEZONE") or "Automatic"
        SCHEDULE_AUTO_UPDATE = True if AUTO_DATE_RANGE else False
        SERVER_ERROR_MAX_RETRY = 3
        EXPIRED_TOKEN_MAX_RETRY = 5
        SKIP_REQUEST_ON_SERVER_ERROR = True
        REQUEST_MAX_RETRIES = int(os.environ.get("REQUEST_MAX_RETRIES") or "5")
        REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS") or "30")
        DRY_RUN_MODE = str(os.environ.get("DRY_RUN_MODE", "False")).lower() in [
            "true",
            "1",
            "yes",
            "y",
        ]
        CALENDAR_SYNC_ENABLED = str(
            os.environ.get("CALENDAR_SYNC_ENABLED", "False")
        ).lower() in [
            "true",
            "1",
            "yes",
            "y",
        ]
        CALENDAR_TOKEN_FILE_PATH = os.environ.get(
            "CALENDAR_TOKEN_FILE_PATH"
        ) or os.path.join(os.path.dirname(TOKEN_FILE_PATH), "google_calendar.token")
        CALENDAR_IDS = (
            tuple(
                part.strip()
                for part in (os.environ.get("CALENDAR_IDS") or "").split(",")
                if part.strip()
            )
            or ("primary",)
        )
        CALENDAR_CLIENT_ID = os.environ.get("CALENDAR_CLIENT_ID") or google_client_id
        CALENDAR_CLIENT_SECRET = (
            os.environ.get("CALENDAR_CLIENT_SECRET") or google_client_secret
        )
        CALENDAR_SYNC_DAYS_BACK = int(os.environ.get("CALENDAR_SYNC_DAYS_BACK") or "7")
        CALENDAR_SYNC_DAYS_AHEAD = int(os.environ.get("CALENDAR_SYNC_DAYS_AHEAD") or "1")
        if min(CALENDAR_SYNC_DAYS_BACK, CALENDAR_SYNC_DAYS_AHEAD) < 0:
            raise ConfigurationError(
                "CALENDAR_SYNC_DAYS_BACK and CALENDAR_SYNC_DAYS_AHEAD must not be negative"
            )
        CALENDAR_API_BASE_URL = (
            os.environ.get("CALENDAR_API_BASE_URL")
            or "https://www.googleapis.com/calendar/v3"
        )
        LOG_LEVEL_NAME = (os.environ.get("LOG_LEVEL") or "DEBUG").strip().upper()
        LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, None)
        if not isinstance(LOG_LEVEL, int):
            LOG_LEVEL = logging.DEBUG
            LOG_LEVEL_NAME = "DEBUG"
        return cls(
            fitbit_log_file_path=FITBIT_LOG_FILE_PATH,
            token_file_path=TOKEN_FILE_PATH,
            overwrite_log_file=OVERWRITE_LOG_FILE,
            fitbit_language=FITBIT_LANGUAGE,
            health_api_provider=HEALTH_API_PROVIDER,
            fitbit_api_base_url=FITBIT_API_BASE_URL,
            google_health_base_url=GOOGLE_HEALTH_BASE_URL,
            google_health_api_version=GOOGLE_HEALTH_API_VERSION,
            google_oauth_token_url=GOOGLE_OAUTH_TOKEN_URL,
            influxdb_version=INFLUXDB_VERSION,
            influxdb_host=INFLUXDB_HOST,
            influxdb_port=INFLUXDB_PORT,
            influxdb_username=INFLUXDB_USERNAME,
            influxdb_password=INFLUXDB_PASSWORD,
            influxdb_database=INFLUXDB_DATABASE,
            influxdb_bucket=INFLUXDB_BUCKET,
            influxdb_org=INFLUXDB_ORG,
            influxdb_token=INFLUXDB_TOKEN,
            influxdb_url=INFLUXDB_URL,
            influxdb_v3_access_token=INFLUXDB_V3_ACCESS_TOKEN,
            client_id=client_id,
            client_secret=client_secret,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            devicename=DEVICENAME,
            user_id=USER_ID,
            device_id=DEVICE_ID,
            device_metadata_state_path=DEVICE_METADATA_STATE_PATH,
            manual_start_date=MANUAL_START_DATE,
            manual_end_date=MANUAL_END_DATE,
            auto_date_range=AUTO_DATE_RANGE,
            auto_update_date_range=auto_update_date_range,
            local_timezone=LOCAL_TIMEZONE,
            schedule_auto_update=SCHEDULE_AUTO_UPDATE,
            server_error_max_retry=SERVER_ERROR_MAX_RETRY,
            expired_token_max_retry=EXPIRED_TOKEN_MAX_RETRY,
            skip_request_on_server_error=SKIP_REQUEST_ON_SERVER_ERROR,
            request_max_retries=REQUEST_MAX_RETRIES,
            request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            dry_run_mode=DRY_RUN_MODE,
            log_level_name=LOG_LEVEL_NAME,
            log_level=LOG_LEVEL,
            calendar_sync_enabled=CALENDAR_SYNC_ENABLED,
            calendar_token_file_path=CALENDAR_TOKEN_FILE_PATH,
            calendar_ids=CALENDAR_IDS,
            calendar_client_id=CALENDAR_CLIENT_ID,
            calendar_client_secret=CALENDAR_CLIENT_SECRET,
            calendar_sync_days_back=CALENDAR_SYNC_DAYS_BACK,
            calendar_sync_days_ahead=CALENDAR_SYNC_DAYS_AHEAD,
            calendar_api_base_url=CALENDAR_API_BASE_URL,
        )
