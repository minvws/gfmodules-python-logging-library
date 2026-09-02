# Changelog

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
