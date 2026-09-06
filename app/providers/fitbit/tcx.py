"""Pure Fitbit payload mappings preserving historical measurements."""
from datetime import datetime, timedelta, timezone
import logging
import pytz
from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields, sleep_stage, utc_timestamp
logger = logging.getLogger(__name__)

import xml.etree.ElementTree as ET

def map_tcx(xml_text, ActivityID, ActivityName, local_timezone):
    records = []
    root = ET.fromstring(xml_text)
    namespace = {'ns': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}
    trackpoints = root.findall('.//ns:Trackpoint', namespace)
    prev_time = None
    prev_distance = None
    for i, trkpt in enumerate(trackpoints):
        time_elem = trkpt.find('ns:Time', namespace)
        lat = trkpt.find('.//ns:LatitudeDegrees', namespace)
        lon = trkpt.find('.//ns:LongitudeDegrees', namespace)
        altitude = trkpt.find('ns:AltitudeMeters', namespace)
        distance = trkpt.find('ns:DistanceMeters', namespace)
        heart_rate = trkpt.find('.//ns:HeartRateBpm/ns:Value', namespace)
        if time_elem is not None and lat is not None and lon is not None:
            current_time = datetime.fromisoformat(time_elem.text.replace('Z', '+00:00'))
            fields = {'lat': float(lat.text), 'lon': float(lon.text)}
            if altitude is not None:
                fields['altitude'] = float(altitude.text)
            if distance is not None:
                fields['distance'] = float(distance.text)
                current_distance = float(distance.text)
            else:
                current_distance = None
            if heart_rate is not None:
                fields['heart_rate'] = int(heart_rate.text)
            if i > 0 and prev_time is not None and (prev_distance is not None) and (current_distance is not None):
                time_diff = (current_time - prev_time).total_seconds()
                distance_diff = current_distance - prev_distance
                if time_diff > 0:
                    speed_mps = distance_diff / time_diff
                    speed_kph = speed_mps * 3.6
                    fields['speed_kph'] = speed_kph
            prev_time = current_time
            prev_distance = current_distance
            records.append({'measurement': 'GPS', 'tags': {'ActivityName': ActivityName}, 'time': datetime.fromisoformat(time_elem.text.replace('Z', '+00:00')).astimezone(pytz.utc).isoformat(), 'fields': {'ActivityId': ActivityID, **fields}})
    return [HealthPoint.from_record(record) for record in records]
