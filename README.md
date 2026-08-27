# GFModules Python Logging Library

Shared logging setup for GFModules Python projects: structured JSON records,
per-stream field routing, request-context middleware, and application lifecycle
events. Each application declares what it logs; the library handles the rest.

> [!CAUTION]
>
> ## Disclaimer
>
> This project and all associated code serve solely as **documentation and demonstration purposes**
> to illustrate potential system communication patterns and architectures.
>
> This codebase:
>
> - Is NOT intended for production use
> - Does NOT represent a final specification
> - Should NOT be considered feature-complete or secure
> - May contain errors, omissions, or oversimplified implementations
> - Has NOT been tested or hardened for real-world scenarios
>
> The code examples are *only* meant to help understand concepts and demonstrate possibilities.
>
> By using or referencing this code, you acknowledge that you do so at your own risk and that
> the authors assume no liability for any consequences of its use.

## Installation

```toml
[tool.poetry.dependencies]
gfmodules-python-logging-library = { git = "https://github.com/minvws/gfmodules-python-logging-library", tag = "v0.1.0", extras = ["fastapi"] }
```

The `fastapi` extra pulls in `starlette` for request-context middleware and
exception handling. Omit it for non-web applications.

## Quick Start

1. **Declare events:** Subclass `DefaultEventCatalogue`, give the system events
   the ids your system numbers them with (`Base.SYS_APP_STARTED.with_id("100601")`),
   and declare your application's own events. Each event defines per-stream field
   allow-lists, which is what keeps application detail out of SIEM.

2. **Configure at boot:** Call `gflog.configure()` with your catalogue and
   settings. Configuration is validated, so mistakes fail at startup rather than
   runtime.

3. **Add middleware:** Wire `RequestContextMiddleware` to capture request context
   (id, ip, endpoint, method, correlation metadata) automatically.

4. **Wire lifecycle:** Compose `gflog.lifespan_logging()` into your application's
   startup, and call `gflog.install_excepthook()` and `gflog.install_signal_handlers()`.

5. **Log events:** Call `gflog.emit(logger, Log.YOUR_EVENT, "message",
   field="value")`. Context is attached automatically.

For detailed steps with examples, see [docs/STARTING_GUIDE.md](docs/STARTING_GUIDE.md).
A complete working FastAPI application is in [examples/](examples/).

## Exception Handling

Exception handlers in Starlette run outside the request middleware, so context
is lost. Use the provided decorators to restore it:

```python
from gfmodules.logging.exceptions import log_unhandled_exception
from gfmodules.logging.middleware import restore_request_context

@restore_request_context
def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log_unhandled_exception(logger, request, exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

app.add_exception_handler(Exception, unhandled_exception_handler)
```

`restore_request_context` rebinds the request context for the handler, so
request id and correlation metadata are available for logging.
`log_unhandled_exception` handles restoration internally, so it works on
undecorated handlers too (but without correlation headers in the response).

## Testing

The library provides context managers and utilities (no pytest dependency):

```python
from gfmodules.logging.testing import (
    assert_catalogue_complete, assert_event_emitted, assert_fields_absent,
    capture_records, capture_stream, recorded_shutdown_reason, reset_for_tests,
)
```

Core patterns:

```python
def test_resource_created_is_logged(records):
    create_resource(resource_id="r-1")
    assert_event_emitted(records, Log.RESOURCE_CREATED, resource_id="r-1")

def test_siem_never_sees_the_owner():
    with capture_stream(LoggingStreams.SIEM) as siem:
        create_resource(resource_id="r-1", owner_id="o-1")
    assert_fields_absent(siem, "owner_id")

def test_catalogue_is_complete():
    assert_catalogue_complete(Log)
```

The per-stream allow-list is exercised when using `capture_stream`, which drives
the real stream filter and formatter. Use `strict_fields=True` in tests to catch
typos (fields that no stream carries).

See [docs/STARTING_GUIDE.md](docs/STARTING_GUIDE.md#testing) for detailed testing examples.

## Record Format

Records are JSON with a fixed structure:

```json
{
  "event_id": "100607",
  "timestamp": "2026-04-12T13:20:00.500000+00:00",
  "level": "INFO",
  "event_description": "resource created",
  "source": "resource_service:88",
  "application_id": "example-service",
  "stream_id": "app",
  "message": { "request_id": "...", "resource_id": "r-1", "owner_id": "o-1" }
}
```

The format is a fixed contract with the log server: `stream_id` identifies the
stream (`app`, `siem`, `public_inspect`, `debug`) and `application_id` identifies
the source application.

## Development

```bash
make check       # lint, type-check, test
make fix         # apply fixes
```

Add `POETRY=true` to run inside the Poetry environment: `make POETRY=true check`.

## Contribution

As stated in the [Disclaimer](#disclaimer) this project and all associated code serve solely as documentation and
demonstration purposes to illustrate potential system communication patterns and architectures.

For that reason we will only accept contributions that fit this goal. We do appreciate any effort from the
community, but because our time is limited it is possible that your PR or issue is closed without a full justification.

If you plan to make non-trivial changes, we recommend opening an issue beforehand where we can discuss your
planned changes. This increases the chance that we might be able to use your contribution
(or it avoids doing work if there are reasons why we wouldn't be able to use it).

Note that all commits should be signed using a gpg key.

When starting to introduce changes, it is important to leave user specific files such as IDE or text-editor settings
outside the repository. For this, create a local `.gitignore` file and configure git like below.

```bash
git config --global core.excludesfile ~/.gitignore
```
