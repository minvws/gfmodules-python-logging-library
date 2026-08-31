# Starting Guide

This guide covers the detailed steps for integrating the logging library into your application.
For a complete working example, see [examples/](../examples/).

## 1. Declare the application's events

Subclass `DefaultEventCatalogue`, which carries the routing for the system events
the library emits on the application's behalf: their level, streams and per-stream
field allow-lists. **It carries no event ids.** Numbering differs per system, so
each application supplies its own with `with_id`, and declares its own events
alongside:

```python
import logging
from gfmodules.logging import DefaultEventCatalogue, LogEvent, LoggingStreams

APP = LoggingStreams.APP
SIEM = LoggingStreams.SIEM

Base = DefaultEventCatalogue


class Log(Base):
    # The system events: this system's ids, the library's routing.
    SYS_APP_STARTED = Base.SYS_APP_STARTED.with_id("100601")
    SYS_APP_STOPPED = Base.SYS_APP_STOPPED.with_id("100602")
    SYS_APP_CRASHED = Base.SYS_APP_CRASHED.with_id("100602")
    SYS_UNHANDLED_EXCEPTION = Base.SYS_UNHANDLED_EXCEPTION.with_id("100604")
    SYS_MISSING_CORRELATION_ID = Base.SYS_MISSING_CORRELATION_ID.with_id("100606")
    # Only where the application logs access: with access_logs off, this one is
    # not demanded and may be left unnumbered.
    ACCESS_REQUEST = Base.ACCESS_REQUEST.with_id("094500")

    # This application's own events.
    RESOURCE_CREATED = LogEvent(
        "100607",
        logging.INFO,
        (APP, SIEM),
        {APP: ("resource_id", "owner_id", "created_by"), SIEM: ("resource_id",)},
    )

    # Optional: per-route event ids for access logging.
    access_event_id = {("POST", "/resources"): "100700"}
```

Where the routing differs too, `replace` changes any combination of the four
attributes and keeps the rest:

```python
class Log(Base):
    SYS_MISSING_CORRELATION_ID = Base.SYS_MISSING_CORRELATION_ID.replace(
        event_id="100606",
        level=logging.WARNING,
        streams=(APP, SIEM),
        fields={APP: ("endpoint", "method"), SIEM: ("endpoint", "method")},
    )
```

`with_id` is `replace(event_id=...)` under a shorter name. Both return a new
event, so the inherited one is never mutated. Restating a whole `LogEvent` still
works, but then the routing is a copy: a later change to the library's routing
will not reach it.

An id left unset fails in `configure()`, naming the slots:

```text
ValueError: Log declares events with no event id: ACCESS_REQUEST, SYS_APP_STARTED. ...
```

Subclass `EventCatalogue` instead to start from nothing, declaring routing as
well as ids for all of `REQUIRED_EVENTS`.

`fields` is a **per-stream allow-list**. A field not listed for a stream never
reaches it, which is what keeps application detail out of SIEM. Correlation
metadata (`request_id`, `ip`, `user_agent`, `client_trace_id`, `correlation_id`)
is always retained. An event with no `fields` sends everything to every stream it
declares.

Field names in `RESERVED_FIELDS` cannot be used: the standard library refuses to
overwrite its own `LogRecord` attributes, so `name`, `module`, `lineno` and the
rest are rejected when the catalogue is validated rather than at log time.

A slot may alias another event where a system has no dedicated id for a trigger:

```python
class Log(EventCatalogue):
    VALIDATION_FAILED = LogEvent("100610", logging.ERROR, (APP, SIEM))
    SCHEMA_MISMATCH = VALIDATION_FAILED
```

The example above does this by giving `SYS_APP_STOPPED` and `SYS_APP_CRASHED` the
same `100602`, because that spec has no separate id for a crash. They are told
apart by level, `CRITICAL` against `INFO`, and by `shutdown_reason`. A log server
splitting purely on `event_id` will not separate them, so give the crash an id of
its own where yours needs one.

## 2. Configure at startup

```python
import gfmodules.logging as gflog

gflog.configure(
    config=config.logging,          # a gflog.ConfigLogging
    loglevel=config.app.loglevel,
    catalogue=Log,
    extra_context_fields=(gflog.ContextField(name="tenant_id", header="X-Tenant-Id"),),
    strict_fields=False,            # True in the test suite, see Testing
)
```

Compose `ConfigLogging` into the application's own settings model:

```python
from gfmodules.logging import ConfigLogging

class Config(BaseModel):
    logging: ConfigLogging
    ...
```

Import `ConfigLogging` from `gfmodules.logging` at every use site. Under mypy's
`no_implicit_reexport`, which strict mode turns on, re-exporting it through the
application's own config module makes every import of it from there fail.

### Configuration reference

| setting | meaning |
| --- | --- |
| `syslog_path` | `host:port`; unset means console only |
| `application_id` | stamped on every JSON record so the log server can tell applications apart; omitted entirely when unset, so set it wherever `syslog_path` is set |
| `include_traces` | include tracebacks in the console stream |
| `debug_logs_in_console` | human-readable console output instead of JSON |
| `correlation_id_expected` | log when a request arrives without a correlation id |
| `trust_forwarded_for` | read the client ip from `X-Forwarded-For`; only where a proxy rewrites it |
| `access_logs` | log a record per request; **off by default**, so nothing is access-logged until an application asks |

`configure()` validates the catalogue, so a missing required event, or one
declaring a reserved field name, fails at boot rather than the first time the
library needs it.

With `access_logs` off, `ACCESS_REQUEST` is no longer part of that contract:
an application that has no access logging duty declares no id for it, and
`RequestContextMiddleware` logs nothing per request. Turning the setting on
without numbering `ACCESS_REQUEST` fails at boot, naming the slot. Applications
whose CI calls `assert_catalogue_complete` pass `access_logs=False` there too,
so the check matches the configuration.

A `syslog_path` the process cannot resolve or connect to is also fatal at boot,
and deliberately so: an application under an audit obligation must not run on
with its records going nowhere. The raised error names `syslog_path` and the
value it was given. Point it at a host reachable from wherever the process runs,
which for a container service name means from inside the compose network.

### The logger tree

The stream handlers are attached to one logger tree, named `app` by default.
**A record logged outside that tree reaches the debug stream only**, so it never
arrives at app, SIEM or public-inspect. Name every logger accordingly:

```python
logger = logging.getLogger("app.resources")   # not __name__
```

An application whose own top level package is not called `app` says so once, and
then logs under its own name instead:

```python
gflog.configure(..., logger_root="svc")       # loggers are svc.resources, svc.api, ...
```

`emit` warns the first time it is given a logger outside the tree, naming it, so
a stream that would otherwise have stayed quietly empty reports itself instead.

### What reaches the console

With `debug_logs_in_console = False` the console carries the app stream only, so
a SIEM-only event is not printed there. That is intended, but during development
it reads as "nothing was logged": check the stream, not the terminal.
`configure()` builds its dict config through `LogConfigBuilder`, which is
exported for an application that needs to inspect or extend it.

## 3. Add the middleware

```python
from gfmodules.logging.middleware import RequestContextMiddleware

app.add_middleware(
    RequestContextMiddleware,
    correlation_id_expected=config.logging.correlation_id_expected,
    capture_body_methods=(),                          # ("POST",) to log request bodies
    max_body_bytes=4096,                              # bodies past this are truncated
    reuse_request_state_id=False,                     # True to honour an upstream request id
    trust_forwarded_for=config.logging.trust_forwarded_for,
)
```

Every event logged while a request is being handled picks up the request id,
client ip, user agent, endpoint, method and correlation metadata automatically,
so call sites never pass them explicitly.

**Access records are not logged unless you ask.** The middleware logs one per
request only where `access_logs` is set in `ConfigLogging`; without it the
context binding above still happens, and nothing else does.

**`configure()` has to run before this.** The middleware reads the setting once,
when it is built, and holds it for the life of the application. Added before
`configure()`, it has nothing to read and says so:

```text
RuntimeError: access logging setting unknown: call gfmodules.logging.configure() before adding the middleware
```

**Request bodies are not logged unless you ask.** A body is the likeliest place
for the data an application least wants in its logs, and the console handler
applies no per-stream allow-list, so anything captured reaches stdout in full.
Name the methods explicitly if you want it, and keep `max_body_bytes` sane.

`ip` comes from the connection, not from `X-Forwarded-For`, because that header
is set by the caller. Set `trust_forwarded_for` only where a proxy in front of
the application rewrites it; then its leftmost entry is used, and only if it
parses as an address.

Per-route access event ids rely on `scope["route"]`, which FastAPI's `APIRoute`
sets and a bare Starlette `Route` does not. Under a plain Starlette router,
access records fall back to the catalogue's `ACCESS_REQUEST` id.

## 4. Wire the application lifecycle

```python
from contextlib import asynccontextmanager

gflog.install_excepthook(logger)
gflog.install_signal_handlers()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with gflog.lifespan_logging(logger, version=read_version(), config_path=config_path):
        await setup_database()
        yield
```

`lifespan_logging` is a composable context manager rather than something you
pass to `FastAPI(lifespan=...)`, so it sits alongside whatever else the
application does at startup. After a crash it emits no stopped event, because the
excepthook has already reported it.

The two events carry their own fields: how the process was configured belongs on
started, what it ended up doing on stopped.

```python
async with gflog.lifespan_logging(
    logger,
    version=read_version(),
    started_fields={"read_only_mode": True},
    stopped_fields=teardown,
):
```

Each mapping is read when its event fires, so `stopped_fields` may be a dict the
application still holds and fills in while it runs. `version` and `config_path`
win on started, `shutdown_reason` on stopped.

Routing still comes from the catalogue, so override `SYS_APP_STARTED` or
`SYS_APP_STOPPED` to name the field in its allow-list or it reaches no stream.

## 5. Log an event

```python
logger = logging.getLogger("app.resources")   # under the configured logger_root

gflog.emit(logger, Log.RESOURCE_CREATED, "resource created",
           fields={"resource_id": "r-1", "owner_id": "o-1"})
```

Fields travel as one mapping, never as loose keyword arguments, pass such a mapping as one field:

```python
gflog.emit(logger, Log.REQUEST_RECEIVED, "request received",
           fields={"request_headers": dict(request.headers)})
```

`source` reports the real call site. An application helper that wraps `emit`
should pass `stacklevel=2` so records point past the wrapper:

```python
def log_rejected_request(logger, reason, fields=None):
    gflog.emit(logger, Log.REQUEST_REJECTED, reason,
               fields={**(fields or {}), "error_reason": reason}, stacklevel=2)
```

## 6. Bind context outside a request

The middleware is not the only way in. `bind_context` attaches context to
anything logged inside the block, which is what a worker or a CLI needs, and
`update_context` adds to what is already bound without replacing it:

```python
from gfmodules.logging import bind_context, update_context

with bind_context({"correlation_id": message.correlation_id}):
    handle(message)          # everything logged in here carries it

# inside a request, once authentication resolves the subject
with update_context({"tenant_id": subject.tenant}):
    ...
```

A field only survives to the record if it was declared, either as a standard
field or through `extra_context_fields`.

`correlation_headers()` returns the correlation id and client trace id as
headers, to pass to a downstream call so the trace does not end here. To read a
single bound value, `collect_context()` returns them all as a dict:

```python
correlation_id = gflog.collect_context().get("correlation_id")
```
