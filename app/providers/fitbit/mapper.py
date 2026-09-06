"""Pure Fitbit payload mappings preserving historical measurements."""
from datetime import datetime, timedelta, timezone
import logging
import pytz
from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields, sleep_stage, utc_timestamp
logger = logging.getLogger(__name__)

def map_intraday(payloads, date_str, measurement_list, device_name, local_timezone):
    records = []
    for measurement in measurement_list:
        data = payloads.get('intraday:' + measurement[0], {})['activities-' + measurement[0] + '-intraday']['dataset']
        if data != None:
            for value in data:
                log_time = datetime.fromisoformat(date_str + 'T' + value['time'])
                utc_time = local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
                records.append({'measurement': measurement[1], 'time': utc_time, 'tags': {'Device': device_name}, 'fields': {'value': int(value['value'])}})
            logger.info('Recorded ' + measurement[1] + ' intraday for date ' + date_str)
        else:
            logger.error('Recording failed : ' + measurement[1] + ' intraday for date ' + date_str)
    return [HealthPoint.from_record(record) for record in records]

def map_spo2(payloads, start_date_str, end_date_str, device_name, local_timezone):
    records = []
    data_list = payloads.get('spo2', [])
    if data_list != None:
        for data in data_list:
            log_time = datetime.fromisoformat(data['dateTime'] + 'T' + '00:00:00')
            utc_time = local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            records.append({'measurement': 'SPO2', 'time': utc_time, 'tags': {'Device': device_name}, 'fields': {'avg': float(data['value']['avg']) if data['value']['avg'] else None, 'max': float(data['value']['max']) if data['value']['max'] else None, 'min': float(data['value']['min']) if data['value']['min'] else None}})
        logger.info('Recorded Avg SPO2 for date ' + start_date_str + ' to ' + end_date_str)
    else:
        logger.error('Recording failed : Avg SPO2 for date ' + start_date_str + ' to ' + end_date_str)
    return [HealthPoint.from_record(record) for record in records]

def map_workouts(payloads, end_date_str, device_name, local_timezone):
    records = []
    next_end_date_str = (datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
    recent_activities_data = payloads.get('activities', {})
    TCX_record_count, TCX_record_limit = (0, 10)
    if recent_activities_data != None:
        for activity in recent_activities_data['activities']:
            fields = {'ActivityId': str(activity['logId']) if activity.get('logId') is not None else None, 'startTime': activity.get('startTime')}
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
            starttime = datetime.fromisoformat(utc_timestamp(activity['startTime'], local_timezone.zone))
            utc_time = starttime.astimezone(pytz.utc).isoformat()
            if activity.get('duration') is not None:
                fields['endTime'] = (starttime + timedelta(milliseconds=float(activity['duration']))).isoformat()
            fields = sanitize_fields(fields)
            try:
                extracted_activity_name = activity['activityName']
            except KeyError as MissingKeyError:
                extracted_activity_name = 'Unknown-Activity'
            ActivityID = fields.get('ActivityId') or utc_time + '-' + extracted_activity_name
            fields['ActivityId'] = ActivityID
            records.append({'measurement': 'Activity Records', 'time': utc_time, 'tags': {'ActivityName': extracted_activity_name}, 'fields': fields})
        logger.info('Fetched 50 recent activities before date ' + end_date_str)
    else:
        logger.error('Fetching 50 recent activities failed : before date ' + end_date_str)
    return [HealthPoint.from_record(record) for record in records]
