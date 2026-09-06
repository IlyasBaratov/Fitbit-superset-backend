"""Minimal write boundary required by ingestion."""
from typing import Protocol
from app.domain.models import HealthPoint

class HealthRepository(Protocol):
    def write(self, points: list[HealthPoint]) -> bool: ...
    def close(self) -> None: ...
