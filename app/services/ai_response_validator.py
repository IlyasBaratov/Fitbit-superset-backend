"""Compatibility import for app.ai.validator."""
import sys
from app.ai import validator as _module
sys.modules[__name__] = _module
