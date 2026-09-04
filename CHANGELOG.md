# Changelog

## Unreleased

### Changed (breaking)

- The console is plain text only. It never emits JSON, which is now the syslog wire
  format alone. The `json` and `json_traces` formatters and the `plain` formatter are
  gone from the generated document, as is the `console` handler; console handlers are
  named `console_app`, `console_siem` and `console_debug`, one per selected stream.
- `debug_logs_in_console` is removed. It was a second name for what `console_streams`
  already says, and setting both printed every debug record twice. Replace
  `debug_logs_in_console=True` with `console_streams=["debug"]`.
- The console carries the SIEM stream by default, where it previously carried the app
  stream alone. A SIEM-only event is now visible in the terminal instead of reading as
  "nothing was logged", and an app-and-SIEM event prints one line per stream, each
  under its own field allow-list. Set `console_streams=["app"]` for the old output.
- Only the debug stream is bound to the root logger, so nothing else reaches stdout for
  records logged outside the application's logger tree.

### Added

- `console_streams` on `ConfigLogging` selects which streams reach stdout, as readable
  text tagged with the stream name, from `app`, `siem` and `debug`. An empty list is
  taken at face value: it silences stdout, so a service can ship to the log server
  alone. An unknown stream name is rejected at boot instead of ignored.
- `include_traces` reaches the plain console formatters, so disabling it now drops
  tracebacks from the console as documented.

### Fixed

- A rejected logging setting is no longer reported as a log server that could not be
  reached, which only `syslog_path` failures should claim.

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
