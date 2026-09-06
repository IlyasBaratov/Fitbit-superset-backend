"""Compatibility import for shared settings."""
import sys
from app.core import config as _config
sys.modules[__name__] = _config
