# Log events

<!-- markdownlint-disable MD013 -->

Generated from `fastapi_app.events:Log` by `gfmodules.logging.event_overview`.
Do not edit by hand.

Each stream lists the events that reach it and the fields they carry there besides the context fields.
*any* means the event has no allow-list, so every field it is logged with reaches the stream.
*none* means the event carries only the context fields there.

## Context fields

Every event carries these on every stream, whenever the request context holds a value for them.

- `request_id`
- `ip`
- `user_agent`
- `client_trace_id`
- `correlation_id`
- `endpoint`
- `method`
- `scope`

## Stream `app`

| Event | Id | Level | Fields |
| --- | --- | --- | --- |
| `SYS_APP_STARTED` | 100601 | INFO | `version`, `config_path` |
| `SYS_APP_STOPPED` | 100602 | INFO | `shutdown_reason`, `last_exception_type` |
| `SYS_APP_CRASHED` | 100602 | CRITICAL | `shutdown_reason`, `last_exception_type` |
| `SYS_UNHANDLED_EXCEPTION` | 100604 | ERROR | `exception_type`, `endpoint`, `method` |
| `SYS_MISSING_CORRELATION_ID` | 100606 | ERROR | `endpoint`, `method` |
| `RESOURCE_CREATED` | 100700 | INFO | `resource_id`, `owner_id`, `created_by` |
| `RESOURCE_DELETED` | 100701 | INFO | `resource_id`, `reason` |
| `LOOKUP_REJECTED` | 100702 | WARNING | `resource_id`, `error_reason` |
| `LOOKUP_MALFORMED` | 100702 | WARNING | `resource_id`, `error_reason` |
| `ACCESS_REQUEST` | 100 | INFO | `endpoint`, `method`, `status_code`, `duration_ms`, `body`, `body_truncated` |

## Stream `siem`

| Event | Id | Level | Fields |
| --- | --- | --- | --- |
| `SYS_APP_STOPPED` | 100602 | INFO | `shutdown_reason` |
| `SYS_APP_CRASHED` | 100602 | CRITICAL | `shutdown_reason` |
| `SYS_UNHANDLED_EXCEPTION` | 100604 | ERROR | `exception_type`, `endpoint`, `method` |
| `SYS_MISSING_CORRELATION_ID` | 100606 | ERROR | `endpoint`, `method` |
| `RESOURCE_CREATED` | 100700 | INFO | `resource_id` |
| `RESOURCE_DELETED` | 100701 | INFO | `resource_id` |

## Access event ids per route

`ACCESS_REQUEST` carries these ids instead of its own on these routes.

| Method | Route | Id |
| --- | --- | --- |
| POST | `/resources` | 100710 |
| DELETE | `/resources/{resource_id}` | 100711 |
