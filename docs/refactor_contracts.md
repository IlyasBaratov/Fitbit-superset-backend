# Refactor compatibility baseline

Preserve every measurement and field in docs/influxdb_schema.md, including unknown Google numeric fields. RestingHR.value and Total Steps.value are historical floats. Identity is UserId/Provider/Device/DeviceId; metadata signatures persist only after writes.

Schedule: current-day heart/steps every 3 minutes; previous day, workouts and token refresh hourly; battery and metadata every 20 minutes; 30-day group every 3 hours, 100-day group every 4 hours, 365-day and unrestricted groups every 6 hours. Initial automatic sync covers today and yesterday. Bulk imports use inclusive overlapping endpoints with offsets 28, 98, 360 and individual intraday dates. Recent activities preserve 50-record semantics and Fitbit TCX limits.

Google filtering falls back from server filters to paginated local-date filtering. Pagination is bounded at 50 pages. Forbidden/unsupported metrics remain unavailable. Worker Automatic timezone uses provider profile/settings; API Automatic uses configured TZ.

Existing API: GET /health, POST /api/ai/{analyze,ask,sleep,activity,workouts,recovery,test}. Preserve strict models, bearer authentication, errors, Gemini structured output/grounding, retries/fallback and cache. Query identity is server controlled.

Baseline: 84 tests. Worker Python 3.10.20; API/local Python 3.14.6. Compose uses ai-api, fitbit-fetch-data, influxdb 1.11 and grafana with persistent host directories. No live deployment or dependency upgrade.


## Mapping parity fixtures

Synthetic payloads in `tests/fixtures/{fitbit,google}_mapping_contract.json` include expected normalized points captured by executing only the original function definitions from commit f8999cc, with all HTTP calls replaced by fixtures. Fitbit covers 25 points across 20 measurements; Google covers 20 points across 19 measurements. Device metadata is covered separately by acknowledgement and discovery tests. The extracted providers must produce identical normalized points for these inputs.

The final audit also fixes the inherited Fitbit empty-activity response failure: a missing or empty daily activity result no longer refers to an uninitialized measurement name.
