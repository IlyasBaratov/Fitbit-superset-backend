"""Compatibility import for app.api.schemas.ai."""
import sys
from app.api.schemas import ai as _module
sys.modules[__name__] = _module
