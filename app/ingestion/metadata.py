"""Acknowledge metadata signatures only after successful database writes."""
import json
import logging
import os
from pathlib import Path
import tempfile
from app.domain.normalization import metadata_signature
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)

class DeviceMetadataState:
    def __init__(self, path, common_tags):
        self.path, self.common_tags = Path(path), dict(common_tags)

    def signature(self, point):
        return metadata_signature(point.fields, self.common_tags)

    def unchanged(self, signature):
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("signature") == signature
        except FileNotFoundError:
            return False
        except (OSError, ValueError, AttributeError):
            logger.warning("Metadata state unavailable; metadata will be retried")
            return False

    def acknowledge(self, signature):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as out:
                temporary = out.name
                json.dump({"signature": signature}, out)
            os.replace(temporary, self.path)
        except OSError:
            raise StorageError("Could not persist metadata acknowledgement") from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
