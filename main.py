from app.providers.fitbit.provider import FitbitProvider
from app.providers.google_health.provider import GoogleHealthProvider
from app.providers.fitbit.client import FitbitClient
from app.providers.google_health import parsing as google_parsing
from app.providers.google_health.parsing import extract_first_numeric, extract_numeric_fields, get_google_payload_key, get_google_datapoint_payload, convert_google_duration_to_seconds, get_google_datapoint_date_string
from app.providers.google_health.client import GoogleHealthClient
from app.providers.http import ProviderHTTPClient, log_metric_http_error
from app.providers.google_health.auth import GoogleTokenManager
from app.providers.fitbit.auth import FitbitTokenManager
from app.storage.influx.repository import InfluxHealthRepository
from app.domain.models import HealthPoint
from app.core.logging import configure_logging
from app.core.config import WorkerSettings
import base64, requests, schedule, time, json, pytz, logging, os, sys
from dotenv import load_dotenv
from requests.exceptions import ConnectionError
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
from health_schema import (
    FIELD_TYPES,
    build_common_tags,
    calculate_bmi,
    metadata_signature,
    parse_google_exercise,
    parse_google_height,
    parse_google_weight,
    prepare_points,
    sanitize_fields,
    sleep_efficiency,
    sleep_stage,
    stable_resource_id,
)


def get_default_auth_headers():
    return {"Authorization": "Bearer " + token_manager.get_access_token(), "Accept": "application/json"}


def get_google_health_api_url(path):
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.get_google_health_api_url(path)


def request_google_data_points_list(data_type, params=None, suppress_http_error_log=False):
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.request_google_data_points_list(data_type, params, suppress_http_error_log)


def request_google_data_points_daily_rollup(data_type, payload):
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.request_google_data_points_daily_rollup(data_type, payload)


def request_google_data_points_rollup(data_type, payload):
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.request_google_data_points_rollup(data_type, payload)














def parse_google_datapoint_timestamp(data_point, data_type=None):
    return google_parsing.parse_google_datapoint_timestamp(data_point, data_type, LOCAL_TIMEZONE)


def get_google_datapoints_for_date(data_type, date_str, page_size=10000):
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.get_google_datapoints_for_date(data_type, date_str, page_size)


def get_google_datapoints_for_date_range(data_type, start_date_str, end_date_str, page_size=10000):
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.get_google_datapoints_for_date_range(data_type, start_date_str, end_date_str, page_size)


def request_data_from_fitbit(url, headers=None, params=None, data=None, request_type="get", suppress_http_error_log=False):
    return transport.request(url, headers=headers, params=params, data=data, request_type=request_type, suppress_http_error_log=suppress_http_error_log)


def Get_New_Access_Token(client_id, client_secret):
    return token_manager.refresh()


def get_common_tags():
    return build_common_tags(USER_ID, HEALTH_API_PROVIDER, DEVICENAME, DEVICE_ID)


def persist_device_metadata_signature():
    global PENDING_DEVICE_METADATA_SIGNATURE
    if not PENDING_DEVICE_METADATA_SIGNATURE:
        return
    os.makedirs(os.path.dirname(DEVICE_METADATA_STATE_PATH) or ".", exist_ok=True)
    with open(DEVICE_METADATA_STATE_PATH, "w") as state_file:
        json.dump({"signature": PENDING_DEVICE_METADATA_SIGNATURE}, state_file)
    PENDING_DEVICE_METADATA_SIGNATURE = None


def write_points_to_influxdb(points):
    repository.common_tags = get_common_tags()
    repository.timezone = getattr(LOCAL_TIMEZONE, "zone", str(LOCAL_TIMEZONE))
    if repository.write([HealthPoint.from_record(point) for point in points]):
        persist_device_metadata_signature()


def get_user_timezone_name():
    if HEALTH_API_PROVIDER == "fitbit":
        profile_data = fitbit_client.profile()
        return profile_data["user"]["timezone"]

    return google_client.get_timezone_name()


def discover_google_device_metadata():
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.discover_google_device_metadata()


def discover_google_device_name():
    google_client.timezone = globals().get("LOCAL_TIMEZONE") if hasattr(globals().get("LOCAL_TIMEZONE"), "localize") else pytz.utc
    return google_client.discover_google_device_name()


def load_device_metadata_signature():
    try:
        with open(DEVICE_METADATA_STATE_PATH, "r") as state_file:
            return (json.load(state_file) or {}).get("signature")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_device_metadata():
    """Queue metadata only when actual provider metadata changes."""
    global GOOGLE_DEVICE_METADATA, PENDING_DEVICE_METADATA_SIGNATURE, DEVICENAME

    observation_time = None
    fields = {}
    if HEALTH_API_PROVIDER == "google":
        GOOGLE_DEVICE_METADATA = discover_google_device_metadata() or GOOGLE_DEVICE_METADATA
        if not GOOGLE_DEVICE_METADATA:
            logging.warning("Device Metadata unavailable for provider 'google'; skipping")
            return
        observation_time = GOOGLE_DEVICE_METADATA.get("_observationTime")
        fields = sanitize_fields({
            "deviceName": GOOGLE_DEVICE_METADATA.get("deviceName"),
            "deviceModel": GOOGLE_DEVICE_METADATA.get("deviceModel"),
            "timezone": getattr(LOCAL_TIMEZONE, "zone", str(LOCAL_TIMEZONE)),
            "firmwareVersion": GOOGLE_DEVICE_METADATA.get("firmwareVersion"),
            "connectionStatus": GOOGLE_DEVICE_METADATA.get("connectionStatus"),
        })
    else:
        try:
            devices = fitbit_client.devices() or []
        except requests.exceptions.HTTPError as error:
            logging.warning("Device metadata unavailable for Fitbit: %s", error)
            devices = []
        if devices:
            device = devices[0]
            observation_time = device.get("lastSyncTime")
            fields = sanitize_fields({
                "deviceName": device.get("deviceVersion") or DEVICENAME,
                "deviceModel": device.get("deviceVersion"),
                "timezone": getattr(LOCAL_TIMEZONE, "zone", str(LOCAL_TIMEZONE)),
                "lastSyncTime": device.get("lastSyncTime"),
                "batteryPercent": device.get("batteryLevel"),
                "firmwareVersion": device.get("firmwareVersion"),
                "connectionStatus": device.get("connectionStatus"),
            })

    if not fields:
        logging.warning("Device Metadata unavailable for provider '%s'; skipping", HEALTH_API_PROVIDER)
        return

    signature = metadata_signature(fields, get_common_tags())
    if signature == load_device_metadata_signature():
        logging.debug("Device Metadata unchanged; skipping duplicate write")
        return

    collected_records.append({
        "measurement": "Device Metadata",
        "time": observation_time or datetime.now(timezone.utc).isoformat(),
        "fields": fields,
    })
    PENDING_DEVICE_METADATA_SIGNATURE = signature
    logging.info("Queued changed Device Metadata for provider '%s'", HEALTH_API_PROVIDER)


def update_working_dates():
    global end_date, start_date, end_date_str, start_date_str
    end_date = datetime.now(LOCAL_TIMEZONE)
    start_date = end_date - timedelta(days=auto_update_date_range)
    end_date_str = end_date.strftime("%Y-%m-%d")
    start_date_str = start_date.strftime("%Y-%m-%d")


def get_battery_level():
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_battery())


def get_intraday_data_limit_1d(date_str, measurement_list):
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_intraday(date_str, measurement_list))


def get_daily_data_limit_30d(start_date_str, end_date_str):
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_daily_group("30d", start_date_str, end_date_str))


def get_daily_data_limit_100d(start_date_str, end_date_str):
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_daily_group("100d", start_date_str, end_date_str))


def get_daily_data_limit_365d(start_date_str, end_date_str):
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_daily_group("365d", start_date_str, end_date_str))


def get_daily_data_limit_none(start_date_str, end_date_str):
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_daily_group("none", start_date_str, end_date_str))




def fetch_latest_activities(end_date_str):
    provider = google_provider if HEALTH_API_PROVIDER == "google" else fitbit_provider
    collected_records.extend(point.as_record() for point in provider.fetch_workouts(end_date_str))


def main():
    """Run the legacy worker explicitly; importing this module is safe."""
    global fitbit_provider, google_provider, fitbit_client, google_client, transport, token_manager, repository, AUTO_DATE_RANGE, DEVICENAME, DEVICE_ID, DEVICE_METADATA_STATE_PATH, DRY_RUN_MODE, EXPIRED_TOKEN_MAX_RETRY, FITBIT_API_BASE_URL, FITBIT_LANGUAGE, FITBIT_LOG_FILE_PATH, GOOGLE_DEVICE_METADATA, GOOGLE_HEALTH_API_VERSION, GOOGLE_HEALTH_BASE_URL, GOOGLE_OAUTH_TOKEN_URL, HEALTH_API_PROVIDER, INFLUXDB_BUCKET, INFLUXDB_DATABASE, INFLUXDB_HOST, INFLUXDB_ORG, INFLUXDB_PASSWORD, INFLUXDB_PORT, INFLUXDB_TOKEN, INFLUXDB_URL, INFLUXDB_USERNAME, INFLUXDB_V3_ACCESS_TOKEN, INFLUXDB_VERSION, LOCAL_TIMEZONE, LOG_LEVEL, LOG_LEVEL_NAME, MANUAL_END_DATE, MANUAL_START_DATE, OVERWRITE_LOG_FILE, PENDING_DEVICE_METADATA_SIGNATURE, REQUEST_MAX_RETRIES, REQUEST_TIMEOUT_SECONDS, SCHEDULE_AUTO_UPDATE, SERVER_ERROR_MAX_RETRY, SKIP_REQUEST_ON_SERVER_ERROR, TOKEN_FILE_PATH, USER_ID, auto_update_date_range, client_id, client_secret, collected_records, date_list, date_range, date_str, demo_point, discovered_device_name, end_date, end_date_str, end_index, google_client_id, google_client_secret, i, influxdb_write_api, influxdbclient, single_day, start_date, start_date_str, start_index
    settings = WorkerSettings.from_env()
    FITBIT_LOG_FILE_PATH = settings.fitbit_log_file_path
    TOKEN_FILE_PATH = settings.token_file_path
    OVERWRITE_LOG_FILE = settings.overwrite_log_file
    FITBIT_LANGUAGE = settings.fitbit_language
    HEALTH_API_PROVIDER = settings.health_api_provider
    FITBIT_API_BASE_URL = settings.fitbit_api_base_url
    GOOGLE_HEALTH_BASE_URL = settings.google_health_base_url
    GOOGLE_HEALTH_API_VERSION = settings.google_health_api_version
    GOOGLE_OAUTH_TOKEN_URL = settings.google_oauth_token_url
    INFLUXDB_VERSION = settings.influxdb_version
    INFLUXDB_HOST = settings.influxdb_host
    INFLUXDB_PORT = settings.influxdb_port
    INFLUXDB_USERNAME = settings.influxdb_username
    INFLUXDB_PASSWORD = settings.influxdb_password
    INFLUXDB_DATABASE = settings.influxdb_database
    INFLUXDB_BUCKET = settings.influxdb_bucket
    INFLUXDB_ORG = settings.influxdb_org
    INFLUXDB_TOKEN = settings.influxdb_token
    INFLUXDB_URL = settings.influxdb_url
    INFLUXDB_V3_ACCESS_TOKEN = settings.influxdb_v3_access_token
    client_id = settings.client_id
    client_secret = settings.client_secret
    google_client_id = settings.google_client_id
    google_client_secret = settings.google_client_secret
    DEVICENAME = settings.devicename
    USER_ID = settings.user_id
    DEVICE_ID = settings.device_id
    DEVICE_METADATA_STATE_PATH = settings.device_metadata_state_path
    MANUAL_START_DATE = settings.manual_start_date
    MANUAL_END_DATE = settings.manual_end_date
    AUTO_DATE_RANGE = settings.auto_date_range
    auto_update_date_range = settings.auto_update_date_range
    LOCAL_TIMEZONE = settings.local_timezone
    SCHEDULE_AUTO_UPDATE = settings.schedule_auto_update
    SERVER_ERROR_MAX_RETRY = settings.server_error_max_retry
    EXPIRED_TOKEN_MAX_RETRY = settings.expired_token_max_retry
    SKIP_REQUEST_ON_SERVER_ERROR = settings.skip_request_on_server_error
    REQUEST_MAX_RETRIES = settings.request_max_retries
    REQUEST_TIMEOUT_SECONDS = settings.request_timeout_seconds
    DRY_RUN_MODE = settings.dry_run_mode
    LOG_LEVEL_NAME = settings.log_level_name
    LOG_LEVEL = settings.log_level

    configure_logging(LOG_LEVEL, FITBIT_LOG_FILE_PATH,
                      secrets=(client_secret, google_client_secret, INFLUXDB_PASSWORD, INFLUXDB_TOKEN, INFLUXDB_V3_ACCESS_TOKEN),
                      overwrite=OVERWRITE_LOG_FILE)

    token_manager = FitbitTokenManager(settings) if HEALTH_API_PROVIDER == "fitbit" else GoogleTokenManager(settings)
    token_manager.refresh()
    transport = ProviderHTTPClient(settings, token_manager)
    google_client = GoogleHealthClient(settings, transport)
    fitbit_client = FitbitClient(settings, transport)

    repository = InfluxHealthRepository(settings, build_common_tags(USER_ID, HEALTH_API_PROVIDER, DEVICENAME, DEVICE_ID), "UTC")

    PENDING_DEVICE_METADATA_SIGNATURE = None

    if LOCAL_TIMEZONE == "Automatic":
        LOCAL_TIMEZONE = pytz.timezone(get_user_timezone_name())
    else:
        LOCAL_TIMEZONE = pytz.timezone(LOCAL_TIMEZONE)

    GOOGLE_DEVICE_METADATA = {}

    if HEALTH_API_PROVIDER == "google":
        GOOGLE_DEVICE_METADATA = discover_google_device_metadata()

    if HEALTH_API_PROVIDER == "google" and DEVICENAME == "Your_Device_Name":
        discovered_device_name = GOOGLE_DEVICE_METADATA.get("deviceName")
        if discovered_device_name:
            logging.info("Auto-detected Google device displayName: %s (override with DEVICENAME env var)", discovered_device_name)
            DEVICENAME = discovered_device_name
        else:
            logging.info("Could not auto-detect device displayName from Google Health API; keeping default '%s'", DEVICENAME)

    google_provider = GoogleHealthProvider(settings, google_client, LOCAL_TIMEZONE, DEVICENAME)
    fitbit_provider = FitbitProvider(settings, fitbit_client, LOCAL_TIMEZONE, DEVICENAME)

    if AUTO_DATE_RANGE:
        end_date = datetime.now(LOCAL_TIMEZONE)
        start_date = end_date - timedelta(days=auto_update_date_range)
        end_date_str = end_date.strftime("%Y-%m-%d")
        start_date_str = start_date.strftime("%Y-%m-%d")
    else:
        start_date_str = MANUAL_START_DATE or input("Enter start date in YYYY-MM-DD format : ")
        end_date_str = MANUAL_END_DATE or input("Enter end date in YYYY-MM-DD format : ")
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

    collected_records = []

    if AUTO_DATE_RANGE:
        date_list = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_date - start_date).days + 1)]
        if len(date_list) > 3:
            logging.warn("Auto schedule update is not meant for more than 3 days at a time, please consider lowering the auto_update_date_range variable to aviod rate limit hit!")
        for date_str in date_list:
            get_intraday_data_limit_1d(date_str, [('heart','HeartRate_Intraday','1sec'),('steps','Steps_Intraday','1min')]) # 2 queries x number of dates ( default 2)
        get_daily_data_limit_30d(start_date_str, end_date_str) # 3 queries
        get_daily_data_limit_100d(start_date_str, end_date_str) # 1 query
        get_daily_data_limit_365d(start_date_str, end_date_str) # 8 queries
        get_daily_data_limit_none(start_date_str, end_date_str) # 1 query
        get_battery_level() # 1 query
        get_device_metadata()
        fetch_latest_activities(end_date_str) # 1 query
        write_points_to_influxdb(collected_records)
        collected_records = []
    else:
        # Do Bulk update----------------------------------------------------------------------------------------------------------------------------

        schedule.every(1).hours.do(lambda : Get_New_Access_Token(client_id,client_secret)) # Auto-refresh tokens every 1 hour
    
        date_list = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_date - start_date).days + 1)]

        def yield_dates_with_gap(date_list, gap):
            start_index = -1*gap
            while start_index < len(date_list)-1:
                start_index  = start_index + gap
                end_index = start_index+gap
                if end_index > len(date_list) - 1:
                    end_index = len(date_list) - 1
                if start_index > len(date_list) - 1:
                    break
                yield (date_list[start_index],date_list[end_index])

        def do_bulk_update(funcname, start_date, end_date):
            global collected_records
            funcname(start_date, end_date)
            schedule.run_pending()
            write_points_to_influxdb(collected_records)
            collected_records = []

        get_device_metadata()
        fetch_latest_activities(date_list[-1])
        write_points_to_influxdb(collected_records)
        collected_records = []
        do_bulk_update(get_daily_data_limit_none, date_list[0], date_list[-1])
        for date_range in yield_dates_with_gap(date_list, 360):
            do_bulk_update(get_daily_data_limit_365d, date_range[0], date_range[1])
        for date_range in yield_dates_with_gap(date_list, 98):
            do_bulk_update(get_daily_data_limit_100d, date_range[0], date_range[1])
        for date_range in yield_dates_with_gap(date_list, 28):
            do_bulk_update(get_daily_data_limit_30d, date_range[0], date_range[1])
        for single_day in date_list:
            do_bulk_update(get_intraday_data_limit_1d, single_day, [('heart','HeartRate_Intraday','1sec'),('steps','Steps_Intraday','1min')])

        logging.info("Success : Bulk update complete for " + start_date_str + " to " + end_date_str)
        print("Bulk update complete!")

    if SCHEDULE_AUTO_UPDATE:
    
        schedule.every(1).hours.do(lambda : Get_New_Access_Token(client_id,client_secret)) # Auto-refresh tokens every 1 hour
        schedule.every(3).minutes.do( lambda : get_intraday_data_limit_1d(end_date_str, [('heart','HeartRate_Intraday','1sec'),('steps','Steps_Intraday','1min')] )) # Auto-refresh detailed HR and steps
        schedule.every(1).hours.do( lambda : get_intraday_data_limit_1d((datetime.strptime(end_date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"), [('heart','HeartRate_Intraday','1sec'),('steps','Steps_Intraday','1min')] )) # Refilling any missing data on previous day end of night due to fitbit sync delay ( see issue #10 )
        schedule.every(20).minutes.do(get_battery_level) # Auto-refresh battery level
        schedule.every(20).minutes.do(get_device_metadata)
        schedule.every(3).hours.do(lambda : get_daily_data_limit_30d(start_date_str, end_date_str))
        schedule.every(4).hours.do(lambda : get_daily_data_limit_100d(start_date_str, end_date_str))
        schedule.every(6).hours.do( lambda : get_daily_data_limit_365d(start_date_str, end_date_str))
        schedule.every(6).hours.do(lambda : get_daily_data_limit_none(start_date_str, end_date_str))
        schedule.every(1).hours.do( lambda : fetch_latest_activities(end_date_str))

        while True:
            schedule.run_pending()
            if len(collected_records) != 0:
                write_points_to_influxdb(collected_records)
                collected_records = []
            time.sleep(30)
            update_working_dates()


if __name__ == "__main__":
    main()
