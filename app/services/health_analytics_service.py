"""Compatibility import for app.ai.analytics."""
import sys
from app.ai import analytics as _module
sys.modules[__name__] = _module
