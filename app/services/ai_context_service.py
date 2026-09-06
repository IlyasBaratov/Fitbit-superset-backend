"""Compatibility import for app.ai.context."""
import sys
from app.ai import context as _module
sys.modules[__name__] = _module
