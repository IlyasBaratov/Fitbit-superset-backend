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

    def __post_init__(self):
        if len(self.api_token) < 32:
            raise ValueError("AI_API_TOKEN must contain at least 32 characters")
        if not self.gemini_key or not self.model:
            raise ValueError("GEMINI_API_KEY and MODEL_NAME are required")
        if not self.user_id or not self.provider or not self.device_id:
            raise ValueError("User, provider and device configuration are required")
        if not 1 <= self.default_days <= self.max_days <= 90:
            raise ValueError("Analysis days must satisfy 1 <= default <= maximum <= 90")
        pytz.timezone(self.timezone)

    @classmethod
    def from_env(cls):
        load_dotenv()
        zone = os.getenv("LOCAL_TIMEZONE", "Automatic")
        return cls(
            api_token=os.getenv("AI_API_TOKEN", ""), gemini_key=os.getenv("GEMINI_API_KEY", ""),
            model=os.getenv("MODEL_NAME") or os.getenv("GEMINI_MODEL", ""),
            user_id=os.getenv("USER_ID", "user_001"), provider=os.getenv("HEALTH_API_PROVIDER", "fitbit"),
            device_id=os.getenv("DEVICE_ID", "fitbit_air_001"),
            timezone=os.getenv("TZ", "America/Los_Angeles") if zone == "Automatic" else zone,
            influx_host=os.getenv("INFLUXDB_HOST", "localhost"), influx_port=int(os.getenv("INFLUXDB_PORT", "8086")),
            influx_database=os.getenv("INFLUXDB_DATABASE", "FitbitHealthStats"),
            influx_username=os.getenv("INFLUXDB_USERNAME", ""), influx_password=os.getenv("INFLUXDB_PASSWORD", ""),
            default_days=int(os.getenv("AI_DEFAULT_ANALYSIS_DAYS", "7")),
            max_days=int(os.getenv("AI_MAX_ANALYSIS_DAYS", "90")))
