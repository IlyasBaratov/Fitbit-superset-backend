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
    if HEALTH_API_PROVIDER == "google":
        logging.warning("Battery level endpoint is not mapped for Google Health API yet. Skipping DeviceBatteryLevel update.")
        return

    device = fitbit_client.devices()[0]
    if device != None:
        collected_records.append({
            "measurement": "DeviceBatteryLevel",
            "time": LOCAL_TIMEZONE.localize(datetime.fromisoformat(device['lastSyncTime'])).astimezone(pytz.utc).isoformat(),
            "fields": {
                "value": float(device['batteryLevel'])
            }
        })
        logging.info("Recorded battery level for " + DEVICENAME)
    else:
        logging.error("Recording battery level failed : " + DEVICENAME)


def get_intraday_data_limit_1d(date_str, measurement_list):
    if HEALTH_API_PROVIDER == "google":
        data_type_mapping = {
            "heart": "heart-rate",
            "steps": "steps"
        }
        for measurement in measurement_list:
            inserted_count = 0
            data_type = data_type_mapping.get(measurement[0])
            if not data_type:
                logging.warning("Google mapping not available for intraday type: %s", measurement[0])
                continue

            try:
                points = get_google_datapoints_for_date(data_type, date_str)
            except requests.exceptions.HTTPError as err:
                log_metric_http_error(f"Google {data_type} for {date_str}", err)
                continue

            for data_point, ts in points:
                payload = get_google_datapoint_payload(data_point, data_type)
                if data_type == "heart-rate":
                    numeric_value = extract_first_numeric(payload.get("beatsPerMinute"))
                elif data_type == "steps":
                    numeric_value = extract_first_numeric(payload.get("count"))
                else:
                    numeric_value = extract_first_numeric(payload)
                if numeric_value is None:
                    continue

                collected_records.append({
                    "measurement": measurement[1],
                    "time": ts,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "value": int(numeric_value)
                    }
                })
                inserted_count += 1
            logging.info("Recorded %s intraday for date %s (Google mode): %s points", measurement[1], date_str, inserted_count)
        return

    for measurement in measurement_list:
        data = fitbit_client.intraday(measurement[0], date_str, measurement[2])["activities-" + measurement[0] + "-intraday"]['dataset']
        if data != None:
            for value in data:
                log_time = datetime.fromisoformat(date_str + "T" + value['time'])
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                collected_records.append({
                        "measurement":  measurement[1],
                        "time": utc_time,
                        "tags": {
                            "Device": DEVICENAME
                        },
                        "fields": {
                            "value": int(value['value'])
                        }
                    })
            logging.info("Recorded " +  measurement[1] + " intraday for date " + date_str)
        else:
            logging.error("Recording failed : " +  measurement[1] + " intraday for date " + date_str)


def get_daily_data_limit_30d(start_date_str, end_date_str):
    if HEALTH_API_PROVIDER == "google":
 
        # --- HRV (daily-heart-rate-variability) ---
        # Google field: dailyHeartRateVariability → { averageHeartRateVariabilityMilliseconds, deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds, nonRemHeartRateBeatsPerMinute, entropy }
        try:
            points = get_google_datapoints_for_date_range("daily-heart-rate-variability", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google HRV", e)
            points = []
        inserted_count = 0
        for data_point, ts in points:
            hrv_fields = data_point.get("dailyHeartRateVariability", {})
            rmssd      = extract_first_numeric(hrv_fields.get("averageHeartRateVariabilityMilliseconds"))
            deep_rmssd = extract_first_numeric(hrv_fields.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds"))
            non_rem_hr = extract_first_numeric(hrv_fields.get("nonRemHeartRateBeatsPerMinute"))
            entropy    = extract_first_numeric(hrv_fields.get("entropy"))
            if rmssd is None and deep_rmssd is None:
                continue
            fields = {}
            if rmssd is not None:
                fields["dailyRmssd"] = rmssd        # matches existing Grafana panel
            if deep_rmssd is not None:
                fields["deepRmssd"] = deep_rmssd    # matches existing Grafana panel
            if non_rem_hr is not None:
                fields["nonRemHeartRateBpm"] = non_rem_hr   # new — Google-only field
            if entropy is not None:
                fields["entropy"] = entropy                  # new — Google-only field
            collected_records.append({
                "measurement": "HRV",
                "time": ts,
                "tags": {"Device": DEVICENAME},
                "fields": fields,
            })
            inserted_count += 1
        if inserted_count:
            logging.info("Recorded HRV for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No HRV records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        # --- Breathing Rate (daily-respiratory-rate) ---
        # Google field: dailyRespiratoryRate → { value } (breaths/min)
        try:
            points = get_google_datapoints_for_date_range("daily-respiratory-rate", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google Breathing Rate", e)
            points = []
        inserted_count = 0
        for data_point, ts in points:
            br_fields = data_point.get("dailyRespiratoryRate", {})
            value = extract_first_numeric(br_fields.get("breathsPerMinute"))
            if value is None:
                continue
            collected_records.append({
                "measurement": "BreathingRate",
                "time": ts,
                "tags": {"Device": DEVICENAME},
                "fields": {"value": float(value)},
            })
            inserted_count += 1
        if inserted_count:
            logging.info("Recorded BR for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No Breathing Rate records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        # --- Skin Temperature Variation (daily-sleep-temperature-derivations) ---
        # Google field: dailySleepTemperatureDerivations → { nightlyRelative }
        try:
            points = get_google_datapoints_for_date_range("daily-sleep-temperature-derivations", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google Skin Temperature", e)
            points = []
        inserted_count = 0
        for data_point, ts in points:
            temp_fields = data_point.get("dailySleepTemperatureDerivations", {})
            nightly  = extract_first_numeric(temp_fields.get("nightlyTemperatureCelsius"))
            baseline = extract_first_numeric(temp_fields.get("baselineTemperatureCelsius"))
            relative = round(nightly - baseline, 4) if nightly is not None and baseline is not None else None
            stddev   = extract_first_numeric(temp_fields.get("relativeNightlyStddev30dCelsius"))
            if relative is None:
                continue
            fields = {"RelativeValue": relative}
            if stddev is not None:
                fields["stddev30d"] = stddev
            if nightly is not None:
                fields["nightlyTemperatureCelsius"] = nightly
            if baseline is not None:
                fields["baselineTemperatureCelsius"] = baseline
            collected_records.append({
                "measurement": "Skin Temperature Variation",
                "time": ts,
                "tags": {"Device": DEVICENAME},
                "fields": fields,
            })
            inserted_count += 1
        if inserted_count:
            logging.info("Recorded Skin Temperature Variation for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No Skin Temp records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        # --- SPO2 Intraday (oxygen-saturation — instantaneous samples) ---
        # Google field: oxygenSaturation → { percentage }
        # Uses sample_time filter (same as heart-rate), walks day by day
        try:
            points = get_google_datapoints_for_date_range("oxygen-saturation", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google SPO2 intraday", e)
            points = []
        inserted_count = 0
        for data_point, ts in points:
            spo2_fields = data_point.get("oxygenSaturation", {})
            value = extract_first_numeric(spo2_fields.get("percentage")) or extract_first_numeric(spo2_fields)
            if value is None:
                continue
            collected_records.append({
                "measurement": "SPO2_Intraday",
                "time": ts,
                "tags": {"Device": DEVICENAME},
                "fields": {"value": float(value)},
            })
            inserted_count += 1
        if inserted_count:
            logging.info("Recorded SPO2 intraday for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No SPO2 intraday records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        # --- Height, Weight, and calculated BMI ---
        height_samples = []
        height_inserted_count = 0
        try:
            height_response = request_google_data_points_list("height", params={"pageSize": 100})
            seen_height_timestamps = set()
            for data_point in height_response.get("dataPoints", []) if isinstance(height_response, dict) else []:
                height_time, height_fields = parse_google_height(data_point)
                if not height_time or not height_fields or height_time in seen_height_timestamps:
                    continue
                seen_height_timestamps.add(height_time)
                height_samples.append((datetime.fromisoformat(height_time.replace("Z", "+00:00")), height_fields["heightMeters"]))
                collected_records.append({
                    "measurement": "height",
                    "time": height_time,
                    "fields": height_fields,
                })
                height_inserted_count += 1
        except requests.exceptions.HTTPError as error:
            log_metric_http_error("Google height", error)
        height_samples.sort(key=lambda item: item[0])
        if height_inserted_count:
            logging.info("Recorded height (Google mode): %s points", height_inserted_count)
        else:
            logging.warning("No height records available in Google mode")

        try:
            points = get_google_datapoints_for_date_range("weight", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google weight", e)
            points = []

        inserted_count = 0
        seen_weight_timestamps = set()
        for data_point, ts in points:
            weight_time, weight_fields = parse_google_weight(data_point)
            weight_time = weight_time or ts
            if not weight_time or not weight_fields or weight_time in seen_weight_timestamps:
                continue
            seen_weight_timestamps.add(weight_time)
            collected_records.append({
                "measurement": "weight",
                "time": weight_time,
                "fields": weight_fields,
            })
            inserted_count += 1

            weight_dt = datetime.fromisoformat(weight_time.replace("Z", "+00:00"))
            eligible_heights = [sample for sample in height_samples if sample[0] <= weight_dt]
            height_meters = eligible_heights[-1][1] if eligible_heights else None
            bmi = calculate_bmi(weight_fields.get("weightKg"), height_meters)
            if bmi is not None:
                collected_records.append({
                    "measurement": "bmi",
                    "time": weight_time,
                    "fields": {
                        "value": bmi,
                        "weightKg": weight_fields.get("weightKg"),
                        "heightMeters": height_meters,
                        "isCalculated": True,
                    },
                })
                inserted_count += 1
        if inserted_count:
            logging.info("Recorded weight and BMI for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No Weight/BMI records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        return  # ← Google path done, skip Fitbit code below
 
    # --- Original Fitbit path (unchanged) ---
    hrv_data_list = fitbit_client.hrv(start_date_str, end_date_str).get('hrv')
    if hrv_data_list != None:
        for data in hrv_data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                    "measurement":  "HRV",
                    "time": utc_time,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "dailyRmssd": float(data["value"]["dailyRmssd"]) if data["value"]["dailyRmssd"] else None,
                        "deepRmssd": float(data["value"]["deepRmssd"]) if data["value"]["deepRmssd"] else None
                    }
                })
        logging.info("Recorded HRV for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed HRV for date " + start_date_str + " to " + end_date_str)
 
    try:
        br_response = fitbit_client.breathing(start_date_str, end_date_str)
        br_data_list = br_response.get("br") if br_response else None
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            logging.warning("Skipping BR for date " + start_date_str + " to " + end_date_str + " due to missing permission (HTTP 403)")
            br_data_list = None
        else:
            raise
    if br_data_list != None:
        for data in br_data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                    "measurement":  "BreathingRate",
                    "time": utc_time,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "value": float(data["value"]["breathingRate"])
                    }
                })
        logging.info("Recorded BR for date " + start_date_str + " to " + end_date_str)
    else:
        logging.warning("Records not found : BR for date " + start_date_str + " to " + end_date_str)
 
    skin_temp_data_list = fitbit_client.skin_temperature(start_date_str, end_date_str).get("tempSkin")
    if skin_temp_data_list != None:
        for temp_record in skin_temp_data_list:
            log_time = datetime.fromisoformat(temp_record["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                    "measurement":  "Skin Temperature Variation",
                    "time": utc_time,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "RelativeValue": float(temp_record["value"]["nightlyRelative"])
                    }
                })
        logging.info("Recorded Skin Temperature Variation for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : Skin Temperature Variation for date " + start_date_str + " to " + end_date_str)
 
    try:
        spo2_data_list = fitbit_client.spo2_intraday(start_date_str, end_date_str)
    except requests.exceptions.HTTPError as e:
        logging.error(f"{e}")
        spo2_data_list = None
    if spo2_data_list != None:
        for days in spo2_data_list:
            data = days["minutes"]
            for record in data:
                log_time = datetime.fromisoformat(record["minute"])
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                collected_records.append({
                        "measurement":  "SPO2_Intraday",
                        "time": utc_time,
                        "tags": {
                            "Device": DEVICENAME
                        },
                        "fields": {
                            "value": float(record["value"]),
                        }
                    })
        logging.info("Recorded SPO2 intraday for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : SPO2 intraday for date " + start_date_str + " to " + end_date_str)
 
    weight_data_list = fitbit_client.weight(start_date_str, end_date_str).get("weight")
    if weight_data_list != None:
        for entry in weight_data_list:
            log_time = datetime.fromisoformat(entry["date"] + "T" + entry["time"])
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                "measurement":  "weight",
                "time": utc_time,
                "tags": {
                    "Device": DEVICENAME
                },
                "fields": {
                    "value": float(entry["weight"]),
                }
            })
            collected_records.append({
                "measurement":  "bmi",
                "time": utc_time,
                "tags": {
                    "Device": DEVICENAME
                },
                "fields": {
                    "value": float(entry["bmi"]),
                }
            })
        logging.info("Recorded weight and BMI for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : weight and BMI for date " + start_date_str + " to " + end_date_str)


def get_daily_data_limit_100d(start_date_str, end_date_str):
    # Google sleep endpoint: data_type = "sleep", session record
    # Google structure differs significantly from Fitbit API:
    #   sleep.summary.minutesAsleep/minutesAwake/minutesInSleepPeriod/stagesSummary
    #   sleep.stages[] → { startTime, endTime, type: AWAKE/LIGHT/DEEP/REM }
    #   sleep.interval → { startTime, endTime }
    # No efficiency field — computed as minutesAsleep/minutesInSleepPeriod * 100
    # All minute values returned as strings, not ints
    if HEALTH_API_PROVIDER == "google":
        try:
            points = get_google_datapoints_for_date_range("sleep", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google sleep", e)
            points = []
        inserted_count = 0
        for data_point, ts in points:
            sleep = data_point.get("sleep", {})
            if not sleep:
                continue

            summary = sleep.get("summary", {})
            stages_summary = summary.get("stagesSummary", [])
            stages_map = {s["type"]: int(s.get("minutes", 0)) for s in stages_summary}

            minutes_asleep      = int(summary.get("minutesAsleep", 0))
            minutes_awake       = int(summary.get("minutesAwake", 0))
            minutes_in_period   = int(summary.get("minutesInSleepPeriod", 0))
            minutes_after_wakeup = int(summary.get("minutesAfterWakeUp", 0))
            minutes_to_fall     = int(summary.get("minutesToFallAsleep", 0))
            minutes_light       = stages_map.get("LIGHT", 0)
            minutes_rem         = stages_map.get("REM", 0)
            minutes_deep        = stages_map.get("DEEP", 0)

            efficiency = sleep_efficiency(minutes_asleep, minutes_in_period, summary.get("efficiency"))
            is_main_sleep = str(bool(sleep.get("metadata", {}).get("processed", True))).lower()
            sleep_session_id = stable_resource_id(data_point.get("name"))
            interval = sleep.get("interval", {})
            start_time_str = interval.get("startTime") or ts
            session_end_time_str = interval.get("endTime")

            collected_records.append({
                "measurement": "Sleep Summary",
                "time": start_time_str,
                "tags": {"Device": DEVICENAME, "isMainSleep": is_main_sleep},
                "fields": sanitize_fields({
                    "SleepSessionId":        sleep_session_id,
                    "efficiency":            efficiency,
                    "minutesAfterWakeup":    minutes_after_wakeup,
                    "minutesAsleep":         minutes_asleep,
                    "minutesToFallAsleep":   minutes_to_fall,
                    "minutesInBed":          minutes_in_period,
                    "minutesAwake":          minutes_awake,
                    "minutesLight":          minutes_light,
                    "minutesREM":            minutes_rem,
                    "minutesDeep":           minutes_deep,
                    "startTime":             start_time_str,
                    "endTime":               session_end_time_str,
                }),
            })
            inserted_count += 1

            # Sleep stage timeline from stages array
            for stage in sleep.get("stages", []):
                stage_time_str = stage.get("startTime")
                if not stage_time_str:
                    continue
                try:
                    stage_dt = datetime.fromisoformat(stage_time_str.replace("Z", "+00:00"))
                    stage_ts = stage_dt.astimezone(pytz.utc).isoformat()
                except ValueError:
                    continue
                level, stage_name = sleep_stage(stage.get("type"))
                stage_end_time_str = stage.get("endTime")
                duration_secs = None
                if stage_end_time_str:
                    try:
                        end_dt = datetime.fromisoformat(stage_end_time_str.replace("Z", "+00:00"))
                        duration_secs = int((end_dt - stage_dt).total_seconds())
                    except ValueError:
                        pass
                collected_records.append({
                    "measurement": "Sleep Levels",
                    "time": stage_ts,
                    "tags": {"Device": DEVICENAME, "isMainSleep": is_main_sleep},
                    "fields": sanitize_fields({
                        "SleepSessionId": sleep_session_id,
                        "level": level,
                        "stageName": stage_name,
                        "duration_seconds": duration_secs,
                    }),
                })

            # Wake marker at end of sleep session
            if session_end_time_str:
                try:
                    wake_dt = datetime.fromisoformat(session_end_time_str.replace("Z", "+00:00"))
                    wake_ts = wake_dt.astimezone(pytz.utc).isoformat()
                    collected_records.append({
                        "measurement": "Sleep Levels",
                        "time": wake_ts,
                        "tags": {"Device": DEVICENAME, "isMainSleep": is_main_sleep},
                        "fields": {"SleepSessionId": sleep_session_id, "level": 3, "stageName": "awake"},
                    })
                except ValueError:
                    pass

        if inserted_count:
            logging.info("Recorded Sleep data for date %s to %s (Google mode): %s sessions", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No Sleep records found for date %s to %s in Google mode", start_date_str, end_date_str)
        return
 
    # --- Original Fitbit path (unchanged) ---
    sleep_data = fitbit_client.sleep(start_date_str, end_date_str).get("sleep")
    if sleep_data != None:
        for record in sleep_data:
            log_time = datetime.fromisoformat(record["startTime"])
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            sleep_session_id = str(record.get("logId")) if record.get("logId") is not None else None
            is_main_sleep = str(bool(record.get("isMainSleep"))).lower()
            try:
                minutesLight = record['levels']['summary']['light']['minutes']
                minutesREM   = record['levels']['summary']['rem']['minutes']
                minutesDeep  = record['levels']['summary']['deep']['minutes']
            except KeyError:
                minutesLight = record['levels']['summary']['asleep']['minutes']
                minutesREM   = record['levels']['summary']['restless']['minutes']
                minutesDeep  = 0
 
            collected_records.append({
                    "measurement":  "Sleep Summary",
                    "time": utc_time,
                    "tags": {
                        "Device": DEVICENAME,
                        "isMainSleep": is_main_sleep,
                    },
                    "fields": sanitize_fields({
                        'SleepSessionId': sleep_session_id,
                        'efficiency': record["efficiency"],
                        'minutesAfterWakeup': record['minutesAfterWakeup'],
                        'minutesAsleep': record['minutesAsleep'],
                        'minutesToFallAsleep': record['minutesToFallAsleep'],
                        'minutesInBed': record['timeInBed'],
                        'minutesAwake': record['minutesAwake'],
                        'minutesLight': minutesLight,
                        'minutesREM': minutesREM,
                        'minutesDeep': minutesDeep,
                        'startTime': record.get("startTime"),
                        'endTime': record.get("endTime"),
                    })
                })
 
            for stage in record['levels']['data']:
                log_time = datetime.fromisoformat(stage["dateTime"])
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                level, stage_name = sleep_stage(stage.get("level"))
                collected_records.append({
                        "measurement":  "Sleep Levels",
                        "time": utc_time,
                        "tags": {
                            "Device": DEVICENAME,
                            "isMainSleep": is_main_sleep,
                        },
                        "fields": {
                            'SleepSessionId': sleep_session_id,
                            'level': level,
                            'stageName': stage_name,
                            'duration_seconds': stage.get("seconds"),
                        }
                    })
            wake_time = datetime.fromisoformat(record["endTime"])
            utc_wake_time = LOCAL_TIMEZONE.localize(wake_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                        "measurement":  "Sleep Levels",
                        "time": utc_wake_time,
                        "tags": {
                            "Device": DEVICENAME,
                            "isMainSleep": is_main_sleep,
                        },
                        "fields": {
                            'SleepSessionId': sleep_session_id,
                            'level': 3,
                            'stageName': "awake",
                        }
                    })
        logging.info("Recorded Sleep data for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : Sleep data for date " + start_date_str + " to " + end_date_str)


def get_daily_data_limit_365d(start_date_str, end_date_str):
    if HEALTH_API_PROVIDER == "google":
 
        # --- Resting Heart Rate (daily-resting-heart-rate) ---
        # Google field: dailyRestingHeartRate → { beatsPerMinute }
        try:
            points = get_google_datapoints_for_date_range("daily-resting-heart-rate", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google Resting Heart Rate", e)
            points = []
        inserted_count = 0
        for data_point, ts in points:
            rhr_fields = data_point.get("dailyRestingHeartRate", {})
            bpm = extract_first_numeric(rhr_fields.get("beatsPerMinute"))
            if bpm is None:
                continue
            collected_records.append({
                "measurement": "RestingHR",
                "time": ts,
                "tags": {"Device": DEVICENAME},
                "fields": {"value": float(bpm)},
            })
            inserted_count += 1
        if inserted_count:
            logging.info("Recorded Resting HR for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No Resting HR records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        # --- HR Zones (active-zone-minutes dailyRollUp) ---
        az_start = datetime.strptime(start_date_str, "%Y-%m-%d")
        az_end   = datetime.strptime(end_date_str,   "%Y-%m-%d")
        current  = az_start
        inserted_count = 0
        while current <= az_end:
            payload = {
                "range": {
                    "start": {"date": {"year": current.year, "month": current.month, "day": current.day},
                            "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0}},
                    "end":   {"date": {"year": current.year, "month": current.month, "day": current.day},
                            "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0}},
                },
                "windowSizeDays": 1,
            }
            try:
                response = request_google_data_points_daily_rollup("active-zone-minutes", payload)
                rollup_points = response.get("rollupDataPoints", []) if isinstance(response, dict) else []
                for rp in rollup_points:
                    azm = rp.get("activeZoneMinutes", {})
                    fields = {}
                    for field_name, provider_key in (
                        ("Fat Burn", "sumInFatBurnHeartZone"),
                        ("Cardio", "sumInCardioHeartZone"),
                        ("Peak", "sumInPeakHeartZone"),
                    ):
                        value = extract_first_numeric(azm.get(provider_key)) if provider_key in azm else None
                        if value is not None:
                            fields[field_name] = int(value)
                    for total_key in ("totalActiveZoneMinutes", "sumActiveZoneMinutes"):
                        total_value = extract_first_numeric(azm.get(total_key)) if total_key in azm else None
                        if total_value is not None:
                            fields["TotalActiveZoneMinutes"] = int(total_value)
                            break
                    if not fields:
                        continue
                    ts = LOCAL_TIMEZONE.localize(current).astimezone(pytz.utc).isoformat()
                    collected_records.append({
                        "measurement": "HR zones",
                        "time": ts,
                        "tags": {"Device": DEVICENAME},
                        "fields": fields,
                    })
                    inserted_count += 1
            except Exception as e:
                logging.warning("Google active-zone-minutes rollup failed for %s: %s", current.strftime("%Y-%m-%d"), str(e))
            current += timedelta(days=1)
        if inserted_count:
            logging.info("Recorded HR Zones for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No HR Zone records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        # --- Activity Minutes via dailyRollUp (steps, total-calories, distance) ---
        # These use the dailyRollUp POST endpoint for aggregated daily totals
        rollup_map = [
            # (data_type,        measurement_name,  field_name,   cast_fn)
            ("steps",            "Total Steps",      "value",      float),
            ("total-calories",   "calories",         "value",      float),
        ]
        
        for data_type, measurement_name, field_name, cast_fn in rollup_map:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date   = datetime.strptime(end_date_str,   "%Y-%m-%d")
            current    = start_date
            inserted_count = 0
            while current <= end_date:
                next_day = current + timedelta(days=1)
                payload = {
                    "range": {
                        "start": {"date": {"year": current.year, "month": current.month, "day": current.day},
                                  "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0}},
                        "end":   {"date": {"year": current.year, "month": current.month, "day": current.day},
                                  "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0}},
                    },
                    "windowSizeDays": 1,
                }
                try:
                    response = request_google_data_points_daily_rollup(data_type, payload)
                except Exception as e:
                    logging.warning("Google dailyRollUp failed for %s on %s: %s", data_type, current.strftime("%Y-%m-%d"), str(e))
                    current = next_day
                    continue
                rollup_points = response.get("rollupDataPoints", []) if isinstance(response, dict) else []
                for rp in rollup_points:
                    # Extract value using explicit field names to avoid picking up year from date objects
                    value = None
                    if data_type == "steps":
                        value = extract_first_numeric(rp.get("steps", {}).get("countSum"))
                    elif data_type == "total-calories":
                        value = extract_first_numeric(rp.get("totalCalories", {}).get("kcalSum"))
                    if value is None:
                        continue
                    # Timestamp: use civilStartTime from rollup point
                    civil_start = rp.get("civilStartTime", {})
                    date_val    = civil_start.get("date", {})
                    try:
                        dt = LOCAL_TIMEZONE.localize(datetime(
                            int(date_val.get("year",  current.year)),
                            int(date_val.get("month", current.month)),
                            int(date_val.get("day",   current.day)),
                        ))
                        ts = dt.astimezone(pytz.utc).isoformat()
                    except Exception:
                        ts = LOCAL_TIMEZONE.localize(current).astimezone(pytz.utc).isoformat()
                    collected_records.append({
                        "measurement": measurement_name,
                        "time": ts,
                        "tags": {"Device": DEVICENAME},
                        "fields": {field_name: cast_fn(value)},
                    })
                    inserted_count += 1
                current = next_day
            if inserted_count:
                logging.info("Recorded %s for date %s to %s (Google mode): %s points", measurement_name, start_date_str, end_date_str, inserted_count)
            else:
                logging.warning("No %s records found for date %s to %s in Google mode", measurement_name, start_date_str, end_date_str)
 
        # --- Distance (separate handling — nested under distance.millimetersSum) ---
        dist_start = datetime.strptime(start_date_str, "%Y-%m-%d")
        dist_end   = datetime.strptime(end_date_str,   "%Y-%m-%d")
        current    = dist_start
        inserted_count = 0
        while current <= dist_end:
            payload = {
                "range": {
                    "start": {"date": {"year": current.year, "month": current.month, "day": current.day},
                              "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0}},
                    "end":   {"date": {"year": current.year, "month": current.month, "day": current.day},
                              "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0}},
                },
                "windowSizeDays": 1,
            }
            try:
                dist_response = request_google_data_points_daily_rollup("distance", payload)
                for rp in dist_response.get("rollupDataPoints", []) if isinstance(dist_response, dict) else []:
                    mm = extract_first_numeric(rp.get("distance", {}).get("millimetersSum"))
                    if mm is not None:
                        ts = LOCAL_TIMEZONE.localize(current).astimezone(pytz.utc).isoformat()
                        collected_records.append({
                            "measurement": "distance",
                            "time": ts,
                            "tags": {"Device": DEVICENAME},
                            "fields": {"value": float(mm / 1_000_000)},  # mm → km
                        })
                        inserted_count += 1
            except Exception as e:
                logging.warning("Google distance rollup failed for %s: %s", current.strftime("%Y-%m-%d"), str(e))
            current += timedelta(days=1)
        if inserted_count:
            logging.info("Recorded distance for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No distance records found for date %s to %s in Google mode", start_date_str, end_date_str)

        # --- Activity Minutes (sedentary-period, active-zone-minutes) ---
        # Using active-zone-minutes for fairlyActive + veryActive approximation
        # minutesSedentary via sedentary-period rollup
        sedentary_start = datetime.strptime(start_date_str, "%Y-%m-%d")
        sedentary_end   = datetime.strptime(end_date_str,   "%Y-%m-%d")
        current = sedentary_start
        inserted_count = 0
        while current <= sedentary_end:
            payload = {
                "range": {
                    "start": {"date": {"year": current.year, "month": current.month, "day": current.day},
                              "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0}},
                    "end":   {"date": {"year": current.year, "month": current.month, "day": current.day},
                              "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0}},
                },
                "windowSizeDays": 1,
            }
            try:
                sedentary_response = request_google_data_points_daily_rollup("sedentary-period", payload)
                rollup_points = sedentary_response.get("rollupDataPoints", []) if isinstance(sedentary_response, dict) else []
                total_sedentary_minutes = 0
                for rp in rollup_points:
                    sedentary_data = rp.get("sedentaryPeriod", {})
                    duration = sedentary_data.get("durationSum") or sedentary_data.get("durationSeconds") or sedentary_data.get("duration")
                    secs = convert_google_duration_to_seconds(duration)
                    if secs is not None:
                        total_sedentary_minutes += secs / 60
                if total_sedentary_minutes > 0:
                    ts = LOCAL_TIMEZONE.localize(current).astimezone(pytz.utc).isoformat()
                    collected_records.append({
                        "measurement": "Activity Minutes",
                        "time": ts,
                        "tags": {"Device": DEVICENAME},
                        "fields": {"minutesSedentary": int(total_sedentary_minutes)},
                    })
                    inserted_count += 1
            except Exception as e:
                logging.warning("Google sedentary-period rollup failed for %s: %s", current.strftime("%Y-%m-%d"), str(e))
            current += timedelta(days=1)
        if inserted_count:
            logging.info("Recorded Activity Minutes (sedentary) for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No sedentary period records found for date %s to %s in Google mode", start_date_str, end_date_str)
 
        return  # ← Google path done
 
    # --- Original Fitbit path (unchanged) ---
    activity_minutes_list = ["minutesSedentary", "minutesLightlyActive", "minutesFairlyActive", "minutesVeryActive"]
    for activity_type in activity_minutes_list:
        activity_minutes_data_list = fitbit_client.activity_series(activity_type, start_date_str, end_date_str).get("activities-tracker-"+activity_type)
        if activity_minutes_data_list != None:
            for data in activity_minutes_data_list:
                log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                collected_records.append({
                        "measurement": "Activity Minutes",
                        "time": utc_time,
                        "tags": {
                            "Device": DEVICENAME
                        },
                        "fields": {
                            activity_type : int(data["value"])
                        }
                    })
            logging.info("Recorded " + activity_type + "for date " + start_date_str + " to " + end_date_str)
        else:
            logging.error("Recording failed : " + activity_type + " for date " + start_date_str + " to " + end_date_str)
 
    activity_others_list = ["distance", "calories", "steps"]
    for activity_type in activity_others_list:
        activity_others_data_list = fitbit_client.activity_series(activity_type, start_date_str, end_date_str).get("activities-tracker-"+activity_type)
        if activity_others_data_list != None:
            for data in activity_others_data_list:
                log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                activity_name = "Total Steps" if activity_type == "steps" else activity_type
                collected_records.append({
                        "measurement": activity_name,
                        "time": utc_time,
                        "tags": {
                            "Device": DEVICENAME
                        },
                        "fields": {
                            "value" : float(data["value"])
                        }
                    })
            logging.info("Recorded " + activity_name + " for date " + start_date_str + " to " + end_date_str)
        else:
            logging.error("Recording failed : " + activity_name + " for date " + start_date_str + " to " + end_date_str)
 
    HR_zones_data_list = fitbit_client.heart_summary(start_date_str, end_date_str).get("activities-heart")
    if HR_zones_data_list != None:
        for data in HR_zones_data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                    "measurement": "HR zones",
                    "time": utc_time,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "Normal" : data["value"]["heartRateZones"][0].get("minutes", 0),
                        "Fat Burn" :  data["value"]["heartRateZones"][1].get("minutes", 0),
                        "Cardio" :  data["value"]["heartRateZones"][2].get("minutes", 0),
                        "Peak" :  data["value"]["heartRateZones"][3].get("minutes", 0)
                    }
                })
            if "restingHeartRate" in data["value"]:
                collected_records.append({
                            "measurement":  "RestingHR",
                            "time": utc_time,
                            "tags": {
                                "Device": DEVICENAME
                            },
                            "fields": {
                                "value": data["value"]["restingHeartRate"]
                            }
                        })
        logging.info("Recorded RHR and HR zones for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : RHR and HR zones for date " + start_date_str + " to " + end_date_str)
 
    HR_zone_minutes_list = fitbit_client.active_zone_minutes(start_date_str, end_date_str).get("activities-active-zone-minutes")
    if HR_zone_minutes_list != None:
        for data in HR_zone_minutes_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            if data.get("value"):
                collected_records.append({
                        "measurement": "HR zones",
                        "time": utc_time,
                        "tags": {
                            "Device": DEVICENAME
                        },
                        "fields": data["value"]
                    })
        logging.info("Recorded HR zone minutes for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : HR zone minutes for date " + start_date_str + " to " + end_date_str)


def get_daily_data_limit_none(start_date_str, end_date_str):
    if HEALTH_API_PROVIDER == "google":
        try:
            points = get_google_datapoints_for_date_range("daily-oxygen-saturation", start_date_str, end_date_str)
        except requests.exceptions.HTTPError as e:
            log_metric_http_error("Google daily oxygen saturation", e)
            points = []

        if points:
            inserted_count = 0
            for data_point, ts in points:
                spo2_fields = data_point.get("dailyOxygenSaturation", {})
                avg_value = extract_first_numeric(spo2_fields.get("averagePercentage"))
                max_value = extract_first_numeric(spo2_fields.get("upperBoundPercentage"))
                min_value = extract_first_numeric(spo2_fields.get("lowerBoundPercentage"))

                if avg_value is None and max_value is None and min_value is None:
                    fallback_value = extract_first_numeric(spo2_fields)
                    avg_value = fallback_value

                collected_records.append({
                    "measurement": "SPO2",
                    "time": ts,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "avg": avg_value,
                        "max": max_value,
                        "min": min_value
                    }
                })
                inserted_count += 1
            logging.info("Recorded Avg SPO2 for date %s to %s (Google mode): %s points", start_date_str, end_date_str, inserted_count)
        else:
            logging.warning("No daily oxygen saturation records found for date %s to %s in Google mode", start_date_str, end_date_str)
        return

    try:
        data_list = fitbit_client.spo2(start_date_str, end_date_str)
    except requests.exceptions.HTTPError as e:
        logging.error(f"{e}")
        data_list = None
    if data_list != None:
        for data in data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                    "measurement":  "SPO2",
                    "time": utc_time,
                    "tags": {
                        "Device": DEVICENAME
                    },
                    "fields": {
                        "avg": float(data["value"]["avg"]) if data["value"]["avg"] else None,
                        "max": float(data["value"]["max"]) if data["value"]["max"] else None,
                        "min": float(data["value"]["min"]) if data["value"]["min"] else None
                    }
                })
        logging.info("Recorded Avg SPO2 for date " + start_date_str + " to " + end_date_str)
    else:
        logging.error("Recording failed : Avg SPO2 for date " + start_date_str + " to " + end_date_str)


def get_tcx_data(tcx_url, ActivityID, ActivityName):
    tcx_headers = {
        "Authorization": "Bearer " + token_manager.get_access_token(),
        "Accept": "application/x-www-form-urlencoded"
    }
    tcx_params = {
            'includePartialTCX': 'false'
        }
    response = fitbit_client.tcx(tcx_url, headers=tcx_headers, params=tcx_params)
    if response.status_code != 200:
        logging.error(f"Error fetching TCX file: {response.status_code}, {response.text}")
    else:
        root = ET.fromstring(response.text)
        namespace = {"ns": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
        trackpoints = root.findall(".//ns:Trackpoint", namespace)
        prev_time = None
        prev_distance = None
        
        for i, trkpt in enumerate(trackpoints):
            time_elem = trkpt.find("ns:Time", namespace)
            lat = trkpt.find(".//ns:LatitudeDegrees", namespace)
            lon = trkpt.find(".//ns:LongitudeDegrees", namespace)
            altitude = trkpt.find("ns:AltitudeMeters", namespace)
            distance = trkpt.find("ns:DistanceMeters", namespace)
            heart_rate = trkpt.find(".//ns:HeartRateBpm/ns:Value", namespace)

            if time_elem is not None and lat is not None:
                current_time = datetime.fromisoformat(time_elem.text.strip("Z"))
                fields = {
                    "lat": float(lat.text),
                    "lon": float(lon.text)
                }
                if altitude is not None:
                    fields["altitude"] = float(altitude.text)
                if distance is not None:
                    fields["distance"] = float(distance.text)
                    current_distance = float(distance.text)
                else:
                    current_distance = None
                if heart_rate is not None:
                    fields["heart_rate"] = int(heart_rate.text)
                if i > 0 and prev_time is not None and prev_distance is not None and current_distance is not None:
                    time_diff = (current_time - prev_time).total_seconds()
                    distance_diff = current_distance - prev_distance
                    if time_diff > 0:
                        speed_mps = distance_diff / time_diff
                        speed_kph = speed_mps * 3.6
                        fields["speed_kph"] = speed_kph
                prev_time = current_time
                prev_distance = current_distance
                
                collected_records.append({
                        "measurement": "GPS",
                        "tags": {
                            "ActivityName": ActivityName
                        },
                        "time": datetime.fromisoformat(time_elem.text.strip("Z")).astimezone(pytz.utc).isoformat(),
                        "fields": {"ActivityId": ActivityID, **fields}
                    })


def fetch_latest_activities(end_date_str):
    if HEALTH_API_PROVIDER == "google":
        # The exercise endpoint returns the most recent records first. We pull the unfiltered
        # latest page (capped at ~50 like the Fitbit list endpoint) instead of trying to filter
        # by date — Google rejects most member-level filters on `exercise` and a same-day filter
        # would miss the 50-most-recent-activities semantics of the original Fitbit call.
        try:
            response = request_google_data_points_list("exercise", params={"pageSize": 100})
        except requests.exceptions.HTTPError as err:
            log_metric_http_error("Google exercise", err)
            response = None

        raw_points = response.get("dataPoints", []) if isinstance(response, dict) else []
        points = []
        for dp in raw_points[:50]:
            ts = parse_google_datapoint_timestamp(dp, "exercise")
            if ts:
                points.append((dp, ts))

        inserted_count = 0
        for data_point, ts in points:
            start_time, fields, extracted_activity_name = parse_google_exercise(data_point)
            if not fields:
                continue
            collected_records.append({
                "measurement": "Activity Records",
                "time": start_time or ts,
                "tags": {
                    "ActivityName": extracted_activity_name
                },
                "fields": fields
            })
            inserted_count += 1
        logging.info("Fetched recent exercises (Google mode): %s points", inserted_count)
        return

    next_end_date_str = (datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    recent_activities_data = fitbit_client.activities(params={'beforeDate': next_end_date_str, 'sort': 'desc', 'limit': 50, 'offset': 0})
    TCX_record_count, TCX_record_limit = 0,10
    if recent_activities_data != None:
        for activity in recent_activities_data['activities']:
            fields = {
                "ActivityId": str(activity["logId"]) if activity.get("logId") is not None else None,
                "startTime": activity.get("startTime"),
            }
            if 'activeDuration' in activity:
                fields['ActiveDuration'] = int(float(activity['activeDuration']) / 1000)
            if 'averageHeartRate' in activity:
                fields['AverageHeartRate'] = int(activity['averageHeartRate'])
            if 'calories' in activity:
                fields['calories'] = int(activity['calories'])
            if 'duration' in activity:
                fields['duration'] = int(float(activity['duration']) / 1000)
            if 'distance' in activity:
                fields['distance'] = float(activity['distance'])
            if 'steps' in activity:
                fields['steps'] = int(activity['steps'])
            starttime = datetime.fromisoformat(activity['startTime'].strip("Z"))
            utc_time = starttime.astimezone(pytz.utc).isoformat()
            if activity.get("duration") is not None:
                fields["endTime"] = (starttime + timedelta(milliseconds=float(activity["duration"]))).isoformat()
            fields = sanitize_fields(fields)
            try:
                extracted_activity_name = activity['activityName']
            except KeyError as MissingKeyError:
                extracted_activity_name = "Unknown-Activity"
            ActivityID = fields.get("ActivityId") or (utc_time + "-" + extracted_activity_name)
            fields["ActivityId"] = ActivityID
            collected_records.append({
                "measurement": "Activity Records",
                "time": utc_time,
                "tags": {
                    "ActivityName": extracted_activity_name
                },
                "fields": fields
            })
            if activity.get("hasGps", False):
                tcx_link = activity.get("tcxLink", False)
                if tcx_link and TCX_record_count <= TCX_record_limit:
                    TCX_record_count += 1
                    try:
                        get_tcx_data(tcx_link, ActivityID, extracted_activity_name)
                        logging.info("Recorded TCX GPS data for " + tcx_link)
                    except Exception as tcx_exception:
                        logging.error("Failed to get GPS Data for " + tcx_link + " : " + str(tcx_exception))
        logging.info("Fetched 50 recent activities before date " + end_date_str)
    else:
        logging.error("Fetching 50 recent activities failed : before date " + end_date_str)


def main():
    """Run the legacy worker explicitly; importing this module is safe."""
    global fitbit_client, google_client, transport, token_manager, repository, AUTO_DATE_RANGE, DEVICENAME, DEVICE_ID, DEVICE_METADATA_STATE_PATH, DRY_RUN_MODE, EXPIRED_TOKEN_MAX_RETRY, FITBIT_API_BASE_URL, FITBIT_LANGUAGE, FITBIT_LOG_FILE_PATH, GOOGLE_DEVICE_METADATA, GOOGLE_HEALTH_API_VERSION, GOOGLE_HEALTH_BASE_URL, GOOGLE_OAUTH_TOKEN_URL, HEALTH_API_PROVIDER, INFLUXDB_BUCKET, INFLUXDB_DATABASE, INFLUXDB_HOST, INFLUXDB_ORG, INFLUXDB_PASSWORD, INFLUXDB_PORT, INFLUXDB_TOKEN, INFLUXDB_URL, INFLUXDB_USERNAME, INFLUXDB_V3_ACCESS_TOKEN, INFLUXDB_VERSION, LOCAL_TIMEZONE, LOG_LEVEL, LOG_LEVEL_NAME, MANUAL_END_DATE, MANUAL_START_DATE, OVERWRITE_LOG_FILE, PENDING_DEVICE_METADATA_SIGNATURE, REQUEST_MAX_RETRIES, REQUEST_TIMEOUT_SECONDS, SCHEDULE_AUTO_UPDATE, SERVER_ERROR_MAX_RETRY, SKIP_REQUEST_ON_SERVER_ERROR, TOKEN_FILE_PATH, USER_ID, auto_update_date_range, client_id, client_secret, collected_records, date_list, date_range, date_str, demo_point, discovered_device_name, end_date, end_date_str, end_index, google_client_id, google_client_secret, i, influxdb_write_api, influxdbclient, single_day, start_date, start_date_str, start_index
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
