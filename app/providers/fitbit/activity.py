"""Pure Fitbit payload mappings preserving historical measurements."""
from datetime import datetime, timedelta, timezone
import logging
import pytz
from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields, sleep_stage, utc_timestamp
logger = logging.getLogger(__name__)

def map_activity(payloads, start_date_str, end_date_str, device_name, local_timezone):
    records = []
    activity_minutes_list = ['minutesSedentary', 'minutesLightlyActive', 'minutesFairlyActive', 'minutesVeryActive']
    for activity_type in activity_minutes_list:
        activity_minutes_data_list = payloads.get('activity_series:' + activity_type, {}).get('activities-tracker-' + activity_type)
        if activity_minutes_data_list != None:
            for data in activity_minutes_data_list:
                log_time = datetime.fromisoformat(data['dateTime'] + 'T' + '00:00:00')
                utc_time = local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
                records.append({'measurement': 'Activity Minutes', 'time': utc_time, 'tags': {'Device': device_name}, 'fields': {activity_type: int(data['value'])}})
            logger.info('Recorded ' + activity_type + 'for date ' + start_date_str + ' to ' + end_date_str)
        else:
            logger.error('Recording failed : ' + activity_type + ' for date ' + start_date_str + ' to ' + end_date_str)
    activity_others_list = ['distance', 'calories', 'steps']
    for activity_type in activity_others_list:
        activity_others_data_list = payloads.get('activity_series:' + activity_type, {}).get('activities-tracker-' + activity_type)
        if activity_others_data_list != None:
            for data in activity_others_data_list:
                log_time = datetime.fromisoformat(data['dateTime'] + 'T' + '00:00:00')
                utc_time = local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
                activity_name = 'Total Steps' if activity_type == 'steps' else activity_type
                records.append({'measurement': activity_name, 'time': utc_time, 'tags': {'Device': device_name}, 'fields': {'value': float(data['value'])}})
            logger.info('Recorded ' + activity_name + ' for date ' + start_date_str + ' to ' + end_date_str)
        else:
            logger.error('Recording failed : ' + activity_name + ' for date ' + start_date_str + ' to ' + end_date_str)
    HR_zones_data_list = payloads.get('heart_summary', {}).get('activities-heart')
    if HR_zones_data_list != None:
        for data in HR_zones_data_list:
            log_time = datetime.fromisoformat(data['dateTime'] + 'T' + '00:00:00')
            utc_time = local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            records.append({'measurement': 'HR zones', 'time': utc_time, 'tags': {'Device': device_name}, 'fields': {'Normal': data['value']['heartRateZones'][0].get('minutes', 0), 'Fat Burn': data['value']['heartRateZones'][1].get('minutes', 0), 'Cardio': data['value']['heartRateZones'][2].get('minutes', 0), 'Peak': data['value']['heartRateZones'][3].get('minutes', 0)}})
            if 'restingHeartRate' in data['value']:
                records.append({'measurement': 'RestingHR', 'time': utc_time, 'tags': {'Device': device_name}, 'fields': {'value': data['value']['restingHeartRate']}})
        logger.info('Recorded RHR and HR zones for date ' + start_date_str + ' to ' + end_date_str)
    else:
        logger.error('Recording failed : RHR and HR zones for date ' + start_date_str + ' to ' + end_date_str)
    HR_zone_minutes_list = payloads.get('active_zone_minutes', {}).get('activities-active-zone-minutes')
    if HR_zone_minutes_list != None:
        for data in HR_zone_minutes_list:
            log_time = datetime.fromisoformat(data['dateTime'] + 'T' + '00:00:00')
            utc_time = local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            if data.get('value'):
                records.append({'measurement': 'HR zones', 'time': utc_time, 'tags': {'Device': device_name}, 'fields': data['value']})
        logger.info('Recorded HR zone minutes for date ' + start_date_str + ' to ' + end_date_str)
    else:
        logger.error('Recording failed : HR zone minutes for date ' + start_date_str + ' to ' + end_date_str)
    return [HealthPoint.from_record(record) for record in records]
