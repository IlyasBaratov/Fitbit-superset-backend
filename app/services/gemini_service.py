"""Compatibility import for app.ai.gemini."""
import sys
from app.ai import gemini as _module
sys.modules[__name__] = _module
