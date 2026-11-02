# Changelog

## Unreleased

### Changed (breaking)

- `color_message` is now in `RESERVED_FIELDS`, so a catalogue that declares it
  as a field fails validation, since the formatters leave it out.
- `RequestContextMiddleware` no longer takes `correlation_id_expected` and
  `trust_forwarded_for` arguments. It reads both from the `ConfigLogging`
  passed to `configure()`, as it already did `access_logs`. Before, both
  settings did nothing unless the application also passed them to the
  middleware by hand, and an argument could contradict the configuration.
  Remove them from `add_middleware()`; passing either now raises a `TypeError`
  when the middleware is built.
- `console_streams` and `syslog_streams` on `ConfigLogging` are typed as lists
  of the stream names each accepts, so an unknown name fails where the
  configuration loads rather than at `configure()`. A type checker now rejects
  a plain `list[str]` passed to them.
- `endpoint` now carries the route template, such as `/patients/{patient_id}`,
  instead of the path the caller sent. A request that matches no route still carries
  the path it was sent to.
- `update_context` is removed in favor of `set_context()`. Its block ended
  before the access record, the unhandled exception record and the records an
  exception handler writes for a refused or invalid request, so a value added
  from a dependency never reached them. Call `set_context()` from the
  dependency instead, without a block.

### Added

- `install_excepthook()` also installs `threading.excepthook`, so an exception
  that ends a thread is logged as `SYS_UNHANDLED_EXCEPTION` with its
  `exception_type` and traceback. Python printed it to stderr before, outside
  every stream. The process keeps running, so it is not logged as a crash.
- `set_context()` adds values to the request's context for the rest of the
  request, even when called inside a `bind_context` block, so they also reach
  the access record, the unhandled exception record and the records of refused
  or invalid requests. It refuses the fields the middleware sets, refuses
  undeclared fields with `strict_fields` on, and does nothing where no context
  is bound, such as in a WebSocket route.

### Changed

- `event_description` on the log server now has control characters escaped
  instead of stripped, so an injection attempt stays visible in the SIEM. A
  newline arrives as `\n` rather than vanishing.
- `set_strict_fields` moved from `gfmodules.logging.events` to
  `gfmodules.logging.strict`, since `set_context()` reads it too.
  `gfmodules.logging` still exports it.

### Fixed

- `install_signal_handlers()` no longer swallows SIGTERM when no handler came
  before it, so workers and cron jobs stop again.
- `lifespan_logging()` now records SIGTERM and SIGINT itself. Calling
  `install_signal_handlers()` at import, as the docs showed, reported
  `graceful` under uvicorn. The call is now optional.
- `lifespan_logging()` now reports an exception raised through it, such as a
  failed startup, as `SYS_APP_CRASHED` instead of a graceful stop.
- The plain-text console output now escapes control characters in the message
  and in field values, so a newline shows as `\n` rather than starting a new
  line. The message used to have them stripped and field values kept them, so
  a newline in a value, such as one in a captured request body, could forge
  extra log lines on stdout.
- Tracebacks in the plain-text console output are now indented by two spaces,
  with control characters other than newlines escaped, so an exception message
  can no longer start a line that passes for a log line.
- Control characters now include the C1 range and the Unicode line and
  paragraph separators, which `str.splitlines()` and some log viewers treat as
  line breaks.
- Uvicorn's `color_message` no longer shows up as a field. Uvicorn attaches it
  to its own records as a colored copy of the message, so the console app
  stream and the debug stream printed ANSI escape codes and an unformatted
  `%d` after every uvicorn startup line.
- `ConfigLogging` now rejects a `syslog_path` that is not `host:port` with a
  port from 1 to 65535, naming the value it was given. A path without a port
  failed at `configure()` with `not enough values to unpack`, and a port that
  is not a number with an `int()` error. A bracketed IPv6 host such as
  `[fd00::1]:5514` now works.
- Access records now follow the catalogue's routing for `ACCESS_REQUEST`. The
  app stream let every record from the access logger through by name, so an
  `ACCESS_REQUEST` routed away from the app stream still reached it.
- The access record for a request whose handler raised now carries
  `status_code` 500, the status Starlette answers it with, instead of `null`.

## 0.7.0 - 2026-11-02

### Changed (breaking)

- Context fields an application declares are now declared on the catalogue as
  `context_fields` instead of passed to `configure()` as
  `extra_context_fields`, which is removed. The event overview reads them from
  there, so it now lists them with the context fields.
- `ALWAYS_KEEP_FIELDS` is removed, since which fields every stream keeps now
  depends on the catalogue. `always_kept_field_names()` returns them.

### Added

- `always_keep` on `ContextField`. A declared context field with
  `always_keep=True` reaches every stream an event routes to, like the standard
  ones, without an entry in each allow-list. Without it, a declared field still
  reaches only the streams whose allow-list names it.

## 0.6.0 - 2026-10-29

### Changed (breaking)

- The debug stream no longer reaches the log server by default. It has no
  filter and no field allow-list, so it sent request bodies, SQL parameters
  and tracebacks to the log server whatever the application configured. Set
  `syslog_streams=["app", "siem", "public_inspect", "debug"]` for the old
  behavior.
- The debug stream on the log server now honours `include_traces`, so
  `include_traces=False` keeps tracebacks off the log server as well.
- `ConfigLogging` now rejects a stream named more than once in
  `console_streams` or `syslog_streams`. The duplicate was silently dropped
  before, which hid a typo or a merge mistake in the configuration.

### Added

- `syslog_streams` on `ConfigLogging` selects which streams (`app`, `siem`,
  `public_inspect`, `debug`) reach the log server. It defaults to
  `["app", "siem", "public_inspect"]`. An empty list sends nothing; an unknown
  stream name fails at boot.
- `gfmodules.logging.event_overview` renders an event catalogue as a markdown
  overview to commit and diff: per stream, each event with its id, level and
  fields, plus the context fields and the per-route access event ids. Generate it
  with `python -m gfmodules.logging.event_overview my_app.events:Log`, and keep it
  current with `assert_event_overview_current` from `gfmodules.logging.testing`.

### Fixed

- `loglevel` now applies to every stream. A logger with a lower level of its
  own, such as SQLAlchemy's with `echo=True` or an application module set to
  `DEBUG`, got records below `loglevel` onto every stream on the log server
  and onto the debug console. Lower `loglevel` to see those records again.
- Records from the `uvicorn` and `uvicorn.error` loggers no longer reach the
  log server on the app stream. They carried no event id, so the log server
  could not place them, and uvicorn's "Exception in ASGI application"
  duplicated the application's `SYS_UNHANDLED_EXCEPTION` record. They still
  reach the log server on the debug stream when `syslog_streams` selects it,
  and the console app stream still shows them.

## 0.5.0 - 2026-09-17

### Changed (breaking)

- `endpoint` and `method` join `ALWAYS_KEEP_FIELDS`: every stream now carries
  them on every event, not only the ones that allow list them.
- `emit()` now rejects any `fields` entry whose name matches a registered
  context field, whether or not `strict_fields` is on. Passing one through
  `fields` would silently forge the bound context value for that record
  instead of the value context actually collected; bind or update the
  context instead.

## 0.4.0 - 2026-09-10

### Added

- `scope` is a new standard context field, extracted from the `X-GF-Scope`
  header and always kept across every stream on every event. Carries
  the authorization scope granted to the calling client, so a service can see
  which scope a caller acted under without declaring anything itself.

### Changed (breaking)

- `access_logs` on `ConfigLogging` now defaults to `True` instead of `False`,
  and `DefaultEventCatalogue.ACCESS_REQUEST` now carries the default event id
  `"100"` instead of an unset one. An application that adds
  `RequestContextMiddleware` and has not touched either setting now gets an
  access record per request without further configuration; set
  `access_logs=False` to opt back out, and override `ACCESS_REQUEST`'s id with
  `.replace(event_id=...)` where a system's own numbering differs.

## 0.3.1 - 2026-09-08

### Added

- `gfmodules.logging.ini.split_comma_separated()` builds a pydantic
  `mode="before"` validator that splits a comma-separated INI value into a
  list, for an application whose own config loader reads INI. Opt-in per
  field; `ConfigLogging` itself stays plain `list[str]`.

## 0.3.0 - 2026-09-07

### Changed (breaking)

- The console is now plain text only; JSON is the syslog wire format alone. The
  `json`/`json_traces`/`plain` formatters and the `console` handler are gone, replaced
  by `console_app`, `console_siem` and `console_debug`, one per selected stream.
- `debug_logs_in_console` is removed; use `console_streams=["debug"]` instead.
- The console carries the SIEM stream by default (previously app only), so an
  app-and-SIEM event now prints one line per stream. Set `console_streams=["app"]` for
  the old behavior.
- Only the debug stream is bound to the root logger, so records logged outside the
  application's logger tree no longer reach stdout by default.

### Added

- `console_streams` on `ConfigLogging` selects which streams (`app`, `siem`, `debug`)
  reach stdout as readable text. An empty list silences stdout; an unknown stream name
  fails at boot.
- `include_traces` now also controls tracebacks in the console formatters.

### Fixed

- A rejected logging setting is no longer misreported as an unreachable log server.

## 0.2.0 - 2026-09-01

### Changed (breaking)

- `emit()`, `EventCatalogue.event()` and `log_unhandled_exception()` take event fields
  through a `fields` mapping instead of loose keyword arguments.
- `lifespan_logging()` replaces `**fields` with `started_fields` and `stopped_fields`,
  both evaluated when their event fires.
- `RequestContextMiddleware` no longer accepts `access_log`; access logging follows
  `ConfigLogging.access_logs`, so `configure()` must run before the middleware is added.
- `DefaultEventCatalogue` ships every event id as `UNSET_EVENT_ID`; applications must
  supply their own numbers via `LogEvent.with_id()` or `LogEvent.replace()`.
  `assert_catalogue_complete()` now fails on unset ids.

### Added

- `access_logs` setting on `ConfigLogging` (default `False`) to enable or disable
  per-request access logging; `ACCESS_REQUEST` is not required when it is off.
- `user_agent` context field, sanitized as free text and kept on every stream.
- `LogEvent.replace()`, `LogEvent.add_fields()` and `LogEvent.with_id()`.
- `unset_event_ids()`, `active_access_logs()` and `register_access_logs()`.

### Fixed

- Reserved record field names in `fields` now raise instead of corrupting the record.
- The `inject` logger is floored at INFO so its bindings stop leaking configuration
  reprs into the logs.

## 0.1.0 - 2026-08-26

- Initial release.
