"""Pure Google health mappings, preserving the collector measurement contracts."""
import logging
from app.domain.models import HealthPoint
from app.providers.google_health.parsing import extract_first_numeric, get_google_datapoint_payload
logger = logging.getLogger(__name__)



def map_intraday(data, date_str, measurement_list, device_name, local_timezone):
    records = []
    data_type_mapping = {'heart': 'heart-rate', 'steps': 'steps'}
    for measurement in measurement_list:
        inserted_count = 0
        data_type = data_type_mapping.get(measurement[0])
        if not data_type:
            logger.warning('Google mapping not available for intraday type: %s', measurement[0])
            continue
        points = data.get(data_type, [])
        for data_point, ts in points:
            payload = get_google_datapoint_payload(data_point, data_type)
            if data_type == 'heart-rate':
                numeric_value = extract_first_numeric(payload.get('beatsPerMinute'))
            elif data_type == 'steps':
                numeric_value = extract_first_numeric(payload.get('count'))
            else:
                numeric_value = extract_first_numeric(payload)
            if numeric_value is None:
                continue
            records.append({'measurement': measurement[1], 'time': ts, 'tags': {'Device': device_name}, 'fields': {'value': int(numeric_value)}})
            inserted_count += 1
        logger.info('Recorded %s intraday for date %s (Google mode): %s points', measurement[1], date_str, inserted_count)
    return [HealthPoint.from_record(record) for record in records]
