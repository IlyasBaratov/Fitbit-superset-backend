"""Provider-independent data transferred from ingestion to storage."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HealthPoint:
    measurement: str
    timestamp: datetime | str
    fields: dict[str, Any]
    tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record):
        return cls(
            record["measurement"],
            record["time"],
            dict(record["fields"]),
            dict(record.get("tags") or {}),
        )

    def as_record(self):
        return {
            "measurement": self.measurement,
            "time": self.timestamp,
            "fields": dict(self.fields),
            "tags": dict(self.tags),
        }
