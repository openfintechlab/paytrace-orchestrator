# PayTrace Orchestrator

## Introduction

`paytrace-orchestrator` is the saga orchestration service for the PayTrace solution. It sits between producer services such as `paytrace-file-ingest-csv` and downstream processing components, subscribes to PayTrace saga/event topics in RabbitMQ, and provides the control point where cross-service workflow coordination can be added.

In the current implementation the service:

- Loads OFTL-prefixed configuration from `.env` and process environment
- Initializes centralized logging
- Connects to RabbitMQ with retry and reconnect behavior
- Declares the configured saga request queue
- Declares and binds the configured saga topic exchange
- Subscribes to configured routing keys such as `files.csv.loaded` and `files.csv.row.failed`
- Consumes messages and acknowledges them after logging receipt

Business saga decisions are intentionally minimal in this project version. `src/main.py::handle_saga_request(...)` is the integration point for adding workflow logic after events arrive.

### Relationship with `paytrace-file-ingest-csv`

`paytrace-file-ingest-csv` publishes file lifecycle events to its configured event exchange:

- EV001: `files.csv.loaded`
- EV002: `files.csv.row.failed`

The orchestrator is configured to bind its saga queue to those same routing keys through:

```text
OFTL_RABITMQ_SAGA_EXCHANGE="paytrace.events"
OFTL_RABITMQ_SAGA_REQUEST_QUEUE="OFTL.SAGA.REQ"
OFTL_RABITMQ_SAGA_SUSCRIBED_TO='["files.csv.loaded","files.csv.row.failed"]'
```

For the two projects to work together, `paytrace-file-ingest-csv` `OFTL_RABITMQ_PUBEVENT_EXCHANGE` must match this service's `OFTL_RABITMQ_SAGA_EXCHANGE`.

## Project Structure

```text
src/
  main.py                  # Entrypoint, banner, RabbitMQ binding, and saga message handler
  domain/
    FileCompletionHandler.py # File completion checks and response CSV generation
  utilities/
    ConfigLoader.py        # OFTL_* configuration loading from .env and environment
    Logging.py             # Centralized logging helper with context sanitization
    DBHelper.py            # PostgreSQL SQLAlchemy engine/session helper
    RabbitMQHelper.py      # RabbitMQ connection, publish, bind, consume, retry, and shutdown helper
tests/
  conftest.py              # Pytest setup
  test_config_loader.py    # ConfigLoader tests
  test_db_helper.py        # DBHelper tests
  test_file_completion_handler.py # Completion and response generation tests
  test_main.py             # Orchestrator startup and saga config tests
  test_rabbitmq_helper.py  # RabbitMQ helper retry/bind/consume tests
```

## Prerequisites

- Python 3.11+
- `uv` installed
- RabbitMQ
- PostgreSQL client/runtime access if using `DBHelper`
- Docker, only when running the containerized service

## Quick Start

### 1. Create local environment file

```bash
cp .env.example .env
```

Update `.env` values for your local RabbitMQ and PostgreSQL environment.

### 2. Install dependencies

```bash
uv sync
```

### 3. Run the orchestrator

```bash
uv run python src/main.py
```

The service validates RabbitMQ connectivity during startup. If RabbitMQ remains unavailable after the configured retry budget, the process exits with status code `99`.

## Run with Docker

### 1. Build the container image

From the `paytrace-orchestrator` project root:

```bash
docker build -t paytrace-orchestrator:latest .
```

### 2. Run with an environment file

```bash
docker run --rm \
  --name paytrace-orchestrator \
  --env-file .env \
  paytrace-orchestrator:latest
```

When RabbitMQ or PostgreSQL are running on the host machine, use `host.docker.internal` for container-to-host connectivity:

```text
OFTL_RABITMQ_HOST="host.docker.internal"
OFTL_POSTGRESDB_HOST="host.docker.internal"
```

### 3. Run with inline environment variables

```bash
docker run --rm \
  --name paytrace-orchestrator \
  -e OFTL_LOG_LEVEL="INFO" \
  -e OFTL_RABITMQ_HOST="host.docker.internal" \
  -e OFTL_RABITMQ_PORT="5672" \
  -e OFTL_RABITMQ_USERNAME="guest" \
  -e OFTL_RABITMQ_PASSWORD_SECRET="guest" \
  -e OFTL_RABITMQ_VHOST="/" \
  -e OFTL_RABITMQ_SAGA_EXCHANGE="paytrace.events" \
  -e OFTL_RABITMQ_SAGA_REQUEST_QUEUE="OFTL.SAGA.REQ" \
  -e OFTL_RABITMQ_SAGA_SUSCRIBED_TO='["files.csv.loaded","files.csv.row.failed"]' \
  paytrace-orchestrator:latest
```

### 4. Verify container logs

```bash
docker logs -f paytrace-orchestrator
```

The orchestrator is a worker process, not an HTTP API, so it does not expose health endpoints in the current implementation.

## Configuration Reference

### Logging

- `OFTL_LOG_LEVEL` (default: `INFO`)
- `OFTL_LOG_FORMAT` (default: `[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s`)

### Service Metadata

- `OFTL_SCA_VERSION` - displayed in the startup banner

### Database

`FileCompletionHandler` uses `DBHelper` to read `oftl_fwcsv_registry` and `oftl_fwcsv_row_dispatch`, set `response_status`, and persist response-file metadata.

- `OFTL_POSTGRESDB_USERNAME`
- `OFTL_POSTGRESDB_PASSWORD`
- `OFTL_POSTGRESDB_HOST`
- `OFTL_POSTGRESDB_PORT`
- `OFTL_POSTGRESDB_NAME` (optional, default: `public`)
- `OFTL_POSTGRESDB_SCHEMA` (optional, default: `public`)
- `OFTL_POSTGRESDB_POOLSIZE` (optional, default: `10`)

### CSV Response Files

- `OFTL_FWCSV_RESPONSE_DIR` (optional, default: `fwcsv/response`) - Directory where completed file response CSVs are written
- `OFTL_ORCHESTRATOR_COMPLETION_WAIT_SECONDS` (optional, default: `5`) - Maximum time to wait for row terminal status after a file event
- `OFTL_ORCHESTRATOR_COMPLETION_POLL_SECONDS` (optional, default: `0.5`) - Poll interval while waiting for row terminal status

Response CSV files are generated with this strict column order:

```text
TransferId,TransactionId,Status,ResponseCode,ResponseMessage,ProcessedTimestamp
```

### RabbitMQ

- `OFTL_RABITMQ_HOST` (default: `localhost`)
- `OFTL_RABITMQ_PORT` (default: `5672`)
- `OFTL_RABITMQ_USERNAME` (default: `guest`)
- `OFTL_RABITMQ_PASSWORD_SECRET` (default: `guest`)
- `OFTL_RABITMQ_VHOST` (default: `/`)
- `OFTL_RABITMQ_HEARTBEAT` (default: `60`)
- `OFTL_RABITMQ_BLOCKED_CONNECTION_TIMEOUT` (default: `30`)
- `OFTL_RABITMQ_CONNECTION_ATTEMPTS` (default: `3`) - Total application-level startup/reconnect attempts
- `OFTL_RABITMQ_CONN_RETRYCOUNT` - Legacy fallback used when `OFTL_RABITMQ_CONNECTION_ATTEMPTS` is not set
- `OFTL_RABITMQ_RETRY_DELAY` (default: `2`)
- `OFTL_RABITMQ_SOCKET_TIMEOUT` (default: `5`)
- `OFTL_RABITMQ_STACK_TIMEOUT` (default: `10`)
- `OFTL_RABITMQ_QUEUE_DURABLE` (default: `true`)
- `OFTL_RABITMQ_MESSAGE_PERSISTENT` (default: `true`)
- `OFTL_RABITMQ_PUBLISH_MANDATORY` (default: `false`)
- `OFTL_RABITMQ_EXCHANGE_DURABLE` (default: `true`)
- `OFTL_RABITMQ_SAGA_EXCHANGE` (default in code: `paytrace.saga`; `.env.example`: `paytrace.events`)
- `OFTL_RABITMQ_SAGA_REQUEST_QUEUE` (default in code: `PAYTRACE.SAGA.REQ`; `.env.example`: `OFTL.SAGA.REQ`)
- `OFTL_RABITMQ_SAGA_SUSCRIBED_TO` (default: `["#"]`)

`OFTL_RABITMQ_SAGA_SUSCRIBED_TO` accepts either a JSON array:

```text
OFTL_RABITMQ_SAGA_SUSCRIBED_TO='["files.csv.loaded","files.csv.row.failed"]'
```

or comma-separated text:

```text
OFTL_RABITMQ_SAGA_SUSCRIBED_TO="files.csv.loaded,files.csv.row.failed"
```

### Runtime Behavior

On startup, the orchestrator:

1. Opens a RabbitMQ connection.
2. Declares `OFTL_RABITMQ_SAGA_EXCHANGE` as a durable topic exchange.
3. Declares `OFTL_RABITMQ_SAGA_REQUEST_QUEUE` as a durable queue.
4. Binds the queue to every routing key in `OFTL_RABITMQ_SAGA_SUSCRIBED_TO`.
5. Starts consuming messages with `prefetch_count=1`.
6. Extracts `file_id` from saga event headers or payload, when present.
7. Delegates completion checks and response generation to `FileCompletionHandler`.
8. Acknowledges each message after `handle_saga_request(...)` completes.

If the message handler raises an exception, the message is negatively acknowledged and requeued.

### File Completion and Response Generation

The saga handler does not own file-completion business rules. It delegates to `src/domain/FileCompletionHandler.py`.

`FileCompletionHandler` considers a file complete only when the count of terminal rows in `oftl_fwcsv_row_dispatch` with status `PROCESSED` or `FAILED` equals `oftl_fwcsv_registry.row_count`. Since row-processed events can arrive before the row status commit is visible, the handler waits briefly and polls before deciding the file is incomplete. Once complete, it conditionally moves `response_status` to `READY_FOR_RESPONSE` so only one worker can generate the response file. After the response CSV is written, it updates `response_status` to `RESP_FILE_GENERATED` and stores `response_file_name` plus `response_file_generated_at`.

If a previous run created the response CSV but stopped before the final registry update, a later event can finalize the existing response file while the registry is still in `READY_FOR_RESPONSE`.

## Testing

Run all tests:

```bash
uv run pytest tests -v
```

Run focused tests:

```bash
uv run pytest tests/test_main.py -v
uv run pytest tests/test_rabbitmq_helper.py -v
uv run pytest tests/test_config_loader.py -v
uv run pytest tests/test_db_helper.py -v
uv run pytest tests/test_file_completion_handler.py -v
```

Run `uv sync` first to ensure dependencies are installed. The current tests cover configuration loading, RabbitMQ retry/bind/consume behavior, DB helper initialization behavior, orchestrator startup wiring, file completion checks, and CSV response generation.

## Major Libraries Used

- `environs` - environment variable parsing
- `python-dotenv` - `.env` file loading
- `pika` - RabbitMQ client
- `sqlalchemy` - database engine/session utilities
- `psycopg2-binary` - PostgreSQL driver
- `pytest` - test framework
