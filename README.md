# paytrace-orchestrator

PayTrace orchestration service skeleton.

The service starts, loads OFTL-prefixed configuration, connects to RabbitMQ, declares the saga request queue, and waits for messages on:

```text
PAYTRACE.SAGA.REQ
```

Business workflow handling is intentionally not implemented in this project scaffold.

## Requirements

- Python 3.11+
- uv
- RabbitMQ
- PostgreSQL client dependencies for `psycopg2-binary`

## Configuration

Copy `.env.example` to `.env` and set the RabbitMQ and PostgreSQL values for your environment. The only queue-specific setting is:

```text
OFTL_RABITMQ_SAGA_REQUEST_QUEUE="PAYTRACE.SAGA.REQ"
```

## Setup

```powershell
uv sync
```

## Run

```powershell
uv run python -m src.main
```

## Test

```powershell
uv run pytest
```
