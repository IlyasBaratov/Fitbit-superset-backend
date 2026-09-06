"""Compatibility import for Influx read access."""
import sys
from app.storage.influx import queries as _queries
sys.modules[__name__] = _queries
