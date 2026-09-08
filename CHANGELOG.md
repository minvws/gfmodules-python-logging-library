# Changelog

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
