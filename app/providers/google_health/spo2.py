"""Pure Google health mappings, preserving the collector measurement contracts."""
import logging
from app.domain.models import HealthPoint
from app.providers.google_health.parsing import extract_first_numeric
logger = logging.getLogger(__name__)



def map_spo2(data, start_date_str, end_date_str, device_name, local_timezone):
    records = []
    points = data.get('daily-oxygen-saturation', [])
    if points:
        inserted_count = 0
        for data_point, ts in points:
            spo2_fields = data_point.get('dailyOxygenSaturation', {})
            avg_value = extract_first_numeric(spo2_fields.get('averagePercentage'))
            max_value = extract_first_numeric(spo2_fields.get('upperBoundPercentage'))
            min_value = extract_first_numeric(spo2_fields.get('lowerBoundPercentage'))
            if avg_value is None and max_value is None and (min_value is None):
                fallback_value = extract_first_numeric(spo2_fields)
                avg_value = fallback_value
            records.append({'measurement': 'SPO2', 'time': ts, 'tags': {'Device': device_name}, 'fields': {'avg': avg_value, 'max': max_value, 'min': min_value}})
            inserted_count += 1
        logger.info('Recorded Avg SPO2 for date %s to %s (Google mode): %s points', start_date_str, end_date_str, inserted_count)
    else:
        logger.warning('No daily oxygen saturation records found for date %s to %s in Google mode', start_date_str, end_date_str)
    return [HealthPoint.from_record(record) for record in records]
