"""Compatibility import for app.ai.service."""
import sys
from app.ai import service as _module
sys.modules[__name__] = _module
