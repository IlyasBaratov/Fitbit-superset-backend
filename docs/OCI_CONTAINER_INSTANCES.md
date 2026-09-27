# Oracle Cloud Container Instances deployment

This repository produces two Linux images: `Dockerfile.api` (FastAPI, port
8000) and `Dockerfile.worker` (scheduled Fitbit/Google Health collection).
`compose.yml` is for a Docker host. Oracle **Container Instances does not run
Compose**; create containers from the built images in the OCI Console or CLI.
The complete deployment places the API and collector in Container Instances
and InfluxDB 1.x plus Grafana on an OCI Compute VM with a block volume. The
database VM is part of this deployment because Container Instances cannot
attach the block storage recommended for InfluxDB.
The worker base image currently publishes `linux/amd64` and `linux/arm64`.
Build for the architecture of the Container Instance shape you select.

## Decide where data lives

| Component | Persistent state | Container Instance setting |
| --- | --- | --- |
| API | Calendar OAuth token, if Calendar connect is used | Mount the same persistent `tokens` directory as the worker at `/app/tokens`; run both with the same UID |
| Worker | Provider OAuth token and device metadata state | Mount persistent `tokens` at `/app/tokens`; set `TOKEN_FILE_PATH=/app/tokens/fitbit.token` and `DEVICE_METADATA_STATE_PATH=/app/tokens/device_metadata_state.json` |
| InfluxDB 1.x | All collected health and Calendar history | Run on the database VM with an attached OCI block volume |
| Grafana | Dashboards, users and settings | Run on the database VM with the same block volume; keep its port private |

The Container Instance root filesystem and empty-directory volumes are
**ephemeral**. OCI says restarting an instance loses the data on ephemeral
storage. Never place the token store, InfluxDB data, or Grafana data there.
OCI File Storage Service (FSS) can persist the token store.
InfluxDB recommends SSD/block-backed storage for its data and write-ahead log;
do not put InfluxDB's live database on FSS without an explicit compatibility
and recovery assessment. For FSS mounts, configure its required network access
and export settings (including privileged source ports and TCP/UDP ports 111
and 2048–2051 between the Container Instance and mount target). Back up and migrate
the existing `tokens/`, `influxdb/`, and `grafana/` directories before changing
the running stack; keep stable `USER_ID` and `DEVICE_ID` values so historical
InfluxDB queries still match. Plan and test FSS permissions for the image UIDs
before moving data. Avoid running the old and new collectors concurrently,
since both can refresh the same OAuth token and write overlapping data.

The API supports **InfluxDB 1.x only**. The worker supports 1.x, 2.x and 3.x.
This deployment keeps InfluxDB 1.x so both work with the same data.

## Database and dashboard VM

Create an OCI Compute VM in a private subnet, attach a block volume in the
same availability domain, format and mount it persistently at
`/srv/fitbit-data`, and install Docker Engine with the Compose plugin. Create
`/srv/fitbit-data/influxdb` and `/srv/fitbit-data/grafana` on that mounted
volume. Confirm the mount with `findmnt /srv/fitbit-data` **before** starting
containers; an unmounted path would silently put health data on the boot disk.
Give the Grafana directory ownership to UID 472. Put
`deploy/oci/compose.database.yml` on the VM with a private `.env` containing:

```dotenv
INFLUXDB_DATABASE=FitbitHealthStats
INFLUXDB_ADMIN_USER=<unique-admin-name>
INFLUXDB_ADMIN_PASSWORD=<unique-admin-password>
INFLUXDB_USERNAME=<application-user>
INFLUXDB_PASSWORD=<application-password>
GF_SECURITY_ADMIN_USER=<grafana-admin-name>
GF_SECURITY_ADMIN_PASSWORD=<unique-grafana-password>
```

Start with `docker compose -f compose.database.yml config --quiet`, then
`docker compose -f compose.database.yml up -d`. The InfluxDB image creates
the database and users only on **first initialization of an empty data
directory**. For an existing database, migrate its data while stopped, then
create/verify users and enable authentication deliberately; changing these
environment variables later does not rewrite existing users. Do not copy the
old unauthenticated data directory over a running container.

Keep the VM's TCP 8086 reachable **only** from the Container Instance subnet
or its network security group. Docker publishes this port on the VM, so the
OCI network rule is essential. Do not allow public ingress to 8086 or 3000.
Grafana is bound to VM loopback at port 3000; use an SSH tunnel or a separately
authenticated HTTPS endpoint to administer it. Configure Grafana's InfluxDB
datasource at `http://influxdb:8086` with the application credentials and
database name. Back up the block volume and test restoring it.

## Build and publish images

From PowerShell in the repository root, substitute your OCI registry region,
tenancy namespace, repository, version, and shape architecture:

```powershell
$registry = '<region-key>.ocir.io'
$namespace = '<tenancy-namespace>'
$repository = '<repository-prefix>'
$version = '<release-version>'
$platform = 'linux/amd64' # use linux/arm64 for an Ampere shape

docker login $registry
docker buildx build --platform $platform -f Dockerfile.api -t "${registry}/${namespace}/${repository}/ai-api:${version}" --push .
docker buildx build --platform $platform -f Dockerfile.worker -t "${registry}/${namespace}/${repository}/collector:${version}" --push .
```

Create the Container Registry repositories and arrange pull permission for
Container Instances first. Use a unique version or image digest when updating;
do not depend on a moving `latest` tag for rollback. Keep `.env`, `tokens/`,
`influxdb/`, `grafana/` and `logs/` out of the image; `.dockerignore` excludes
them. Do not copy credentials into a Dockerfile or registry image.

## Create the Container Instance

Use a subnet that can reach the registry, Google/Fitbit/Gemini endpoints and
your InfluxDB endpoint. In the OCI Console, go to **Developer Services →
Containers & Artifacts → Container Instances → Create container instance**.
Choose a shape matching the image architecture, then configure each container
and its environment variables. OCI's instance restart policy replaces the
Compose `restart` setting. Container Instances do not apply Compose's
`depends_on`, bind mounts, health checks, or service DNS names.

For the **API container**:

- Image: the published `ai-api` image; keep its entrypoint and port 8000.
- Set `AI_API_TOKEN` to a unique random value of at least 32 characters,
  `GEMINI_API_KEY`, and `MODEL_NAME` (or `GEMINI_MODEL`).
- Set `INFLUXDB_HOST`, `INFLUXDB_PORT=8086`, `INFLUXDB_DATABASE`,
  `INFLUXDB_USERNAME`, and `INFLUXDB_PASSWORD` for the reachable 1.x database.
- Preserve `USER_ID`, `DEVICE_ID`, `HEALTH_API_PROVIDER`, `TZ`, and
  `LOCAL_TIMEZONE` from the existing stack.
- If using the API Calendar connection, mount persistent tokens at
  `/app/tokens`, set `CALENDAR_TOKEN_FILE_PATH=/app/tokens/google_calendar.token`,
  `CALENDAR_CLIENT_ID`, `CALENDAR_CLIENT_SECRET`, and
  `CALENDAR_REDIRECT_URI=https://<api-domain>/api/calendar/callback`.
  Register that **exact** URI with the Google OAuth client. Run the API as the
  same UID as the worker so it can read the token file (mode `0600`).
- Enable the read-only root filesystem option only after mounting a writable
  `/tmp` empty directory and the token directory if Calendar connect is used.

For the **collector container**, when deploying it:

- Image: the published `collector` image; keep its entrypoint. It exposes no
  public port.
- Set `HEALTH_API_PROVIDER` and the matching Fitbit `CLIENT_ID` /
  `CLIENT_SECRET` or Google `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
- Set `INFLUXDB_VERSION=1`, `INFLUXDB_HOST`, `INFLUXDB_PORT=8086`,
  `INFLUXDB_DATABASE`, `INFLUXDB_USERNAME`, and `INFLUXDB_PASSWORD`.
- Set `TOKEN_FILE_PATH=/app/tokens/fitbit.token`,
  `DEVICE_METADATA_STATE_PATH=/app/tokens/device_metadata_state.json`,
  `FITBIT_LOG_FILE_PATH=/tmp/fitbit.log` (stdout is also logged),
  `AUTO_DATE_RANGE=true`, and the same identity/timezone values as the API.
- Mount the persistent token directory at `/app/tokens`. If enabling Calendar
  sync, also set `CALENDAR_SYNC_ENABLED=true`, Calendar credentials/IDs, and
  `CALENDAR_TOKEN_FILE_PATH=/app/tokens/google_calendar.token`.

Do not put the InfluxDB or Grafana ports in an internet-facing security rule.
For the public API, use a domain and an HTTPS endpoint (for example, an OCI
Load Balancer with a managed certificate) forwarding to port 8000; limit the
container's network security group ingress to the load balancer. Keep the
database private. The API's `/health` endpoint is a process liveness check;
it does not test InfluxDB or Gemini. All health and AI data endpoints use the
`Authorization: Bearer <AI_API_TOKEN>` header.

## Verify and operate

1. Check the API container is running and the HTTPS `/health` endpoint returns
   `{"status":"ok"}`.
2. Call `GET /api/devices` with the bearer token to verify the API can read
   InfluxDB. A healthy `/health` alone is insufficient.
3. Check collector logs for a successful provider sync and new InfluxDB points.
   If Calendar is used, check `/api/calendar/status` and a Calendar Events query.
4. Restart the Container Instance and repeat the checks. Verify OAuth tokens,
   health history and dashboards survived before removing the old deployment.
5. Keep a separate backup of the persistent database and tokens. FSS persistence
   alone is not a backup.

OCI references: [create a Container Instance](https://docs.oracle.com/en-us/iaas/Content/container-instances/creating-a-container-instance.htm),
[restart and ephemeral data](https://docs.oracle.com/en-us/iaas/Content/container-instances/restarting-a-container-instance.htm),
[mount FSS](https://docs.oracle.com/en-us/iaas/Content/container-instances/creating-mounting-fss.htm),
[Container Registry](https://docs.oracle.com/iaas/Content/Registry/),
[load balancer HTTPS](https://docs.oracle.com/en-us/iaas/Content/Balance/Tasks/managingloadbalancer_topic-Creating_Load_Balancers.htm),
[InfluxDB storage guidance](https://docs.influxdata.com/influxdb/v1/guides/hardware_sizing/).
