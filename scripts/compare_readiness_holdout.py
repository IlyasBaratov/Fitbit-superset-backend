"""Report non-blocking v0.3 holdout comparisons from factual stored-health snapshots."""

from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

from app.api.readiness_score_service import ReadinessScoreReadService
from app.core.config import Settings
from app.scores.sleep import aware_utc


SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "readiness_real_health_snapshot.json"


class SnapshotRepository:
    def __init__(self, rows):
        self.rows = rows

    def query(self, measurement, start, end):
        return [
            row for row in self.rows[measurement]
            if start <= aware_utc(row["time"]) < end
        ]


def main():
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if document["source"] != "stored_health_influxdb_owner_data":
        raise ValueError("Holdout input is not the factual stored-health snapshot")
    settings = Settings(api_token="r" * 40, gemini_key="unused", model="unused")
    clock = lambda: datetime(2026, 10, 8, 19, tzinfo=timezone.utc)
    service = ReadinessScoreReadService(
        settings, SnapshotRepository(document["measurements"]), clock
    )
    results = service.read("3d").days
    errors = []
    for day in results:
        if day.observed_score is None or day.calculated_score is None:
            continue
        error = day.calculated_score - day.observed_score
        errors.append(error)
        print(f"{day.date}: observed={day.observed_score} calculated={day.calculated_score} signed_error={error:+d}")
    if errors:
        print(
            f"MAE={statistics.mean(abs(value) for value in errors):.3f} "
            f"median_abs_error={statistics.median(abs(value) for value in errors):.3f} "
            f"max_abs_error={max(abs(value) for value in errors)} "
            f"signed_mean_error={statistics.mean(errors):+.3f}"
        )


if __name__ == "__main__":
    main()
