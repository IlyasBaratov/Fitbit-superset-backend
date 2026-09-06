# Refactor compatibility baseline

Preserve every measurement and field in docs/influxdb_schema.md, including unknown Google numeric fields. RestingHR.value and Total Steps.value are historical floats. Identity is UserId/Provider/Device/DeviceId; metadata signatures persist only after writes.

Schedule: current-day heart/steps every 3 minutes; previous day, workouts and token refresh hourly; battery and metadata every 20 minutes; 30-day group every 3 hours, 100-day group every 4 hours, 365-day and unrestricted groups every 6 hours. Initial automatic sync covers today and yesterday. Bulk imports use inclusive overlapping endpoints with offsets 28, 98, 360 and individual intraday dates. Recent activities preserve 50-record semantics and Fitbit TCX limits.

Google filtering falls back from server filters to paginated local-date filtering. Pagination is bounded at 50 pages. Forbidden/unsupported metrics remain unavailable. Worker Automatic timezone uses provider profile/settings; API Automatic uses configured TZ.

Existing API: GET /health, POST /api/ai/{analyze,ask,sleep,activity,workouts,recovery,test}. Preserve strict models, bearer authentication, errors, Gemini structured output/grounding, retries/fallback and cache. Query identity is server controlled.

Baseline: 84 tests. Worker Python 3.10.20; API/local Python 3.14.6. Compose uses ai-api, fitbit-fetch-data, influxdb 1.11 and grafana with persistent host directories. No live deployment or dependency upgrade.
