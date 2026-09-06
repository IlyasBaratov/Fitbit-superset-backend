"""Pure Google health mappings, preserving the collector measurement contracts."""
import logging
from app.domain.models import HealthPoint
from app.providers.google_health.parsing import parse_google_datapoint_timestamp
from app.providers.google_health.mapper import parse_google_exercise
logger = logging.getLogger(__name__)



def map_workouts(data, device_name, local_timezone):
    records = []
    response = data.get('exercise', {})
    raw_points = response.get('dataPoints', []) if isinstance(response, dict) else []
    points = []
    for dp in raw_points[:50]:
        ts = parse_google_datapoint_timestamp(dp, 'exercise', local_timezone=local_timezone)
        if ts:
            points.append((dp, ts))
    inserted_count = 0
    for data_point, ts in points:
        start_time, fields, extracted_activity_name = parse_google_exercise(data_point)
        if not fields:
            continue
        records.append({'measurement': 'Activity Records', 'time': start_time or ts, 'tags': {'ActivityName': extracted_activity_name}, 'fields': fields})
        inserted_count += 1
    logger.info('Fetched recent exercises (Google mode): %s points', inserted_count)
    return [HealthPoint.from_record(record) for record in records]
