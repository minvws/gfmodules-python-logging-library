# Example integration

A complete, working FastAPI application wired up with this library. It is small
enough to read in one sitting and it runs as part of the test suite, so it
cannot drift away from the library it demonstrates.

The domain is deliberately empty: it creates and deletes a "resource" with an
owner, and nothing about it means anything. Every name here is a placeholder for
whatever your application actually deals in.

Read it in this order:

| file | what it shows |
| --- | --- |
| [fastapi_app/events.py](fastapi_app/events.py) | the event catalogue: required slots, the application's own events, per-stream field allow-lists, an alias, per-route access ids |
| [fastapi_app/config.py](fastapi_app/config.py) | `ConfigLogging` composed into the application's own settings |
| [fastapi_app/app.py](fastapi_app/app.py) | the whole integration: `configure()`, the middleware, the lifespan, the exception handler |
| [fastapi_app/service.py](fastapi_app/service.py) | ordinary domain code that logs, and the `stacklevel` idiom for a wrapper |
| [fastapi_app/test_logging.py](fastapi_app/test_logging.py) | the tests an application should have about its own logging |
| [fastapi_app/conftest.py](fastapi_app/conftest.py) | the fixtures those tests need |

## Running it

From the repository root:

```sh
poetry run pytest examples
```

`poetry run pytest` runs it too, after the library's own suite.

## Wiring your own application

Four things have to happen, in this order:

1. **Declare a catalogue.** Subclass `EventCatalogue` and fill every slot in
   `REQUIRED_EVENTS`, plus the application's own events. Give each event a
   per-stream `fields` allow-list.
2. **Call `configure()` before anything logs.** In the example this is
   `setup_logging()`, called from the entry point. It validates the catalogue,
   so a slot you forgot stops the process at boot.
3. **Add `RequestContextMiddleware` last**, so it runs outermost and wraps every
   route and handler registered before it.
4. **Compose `lifespan_logging` into your own lifespan** rather than passing it
   to `FastAPI(lifespan=...)`, so your startup work still fits alongside it.

After that, call sites just log: `gflog.emit(logger, Log.SOMETHING, "message",
field="value")`. The request id, client ip, endpoint, method and correlation
metadata are attached for you.

## The part worth copying most carefully

`fields` on each event is a per-stream allow-list, and it is what keeps
application detail out of SIEM. In the example, `RESOURCE_CREATED` carries
`resource_id`, `owner_id` and `created_by`, but SIEM is allow-listed for
`resource_id` alone. `test_siem_sees_the_resource_id_and_nothing_else` asserts
that the other two never arrive there.

Two mistakes to avoid:

- **Leaving `fields` off an event that declares SIEM.** An event with no
  `fields` applies no routing at all, so every field the call site passed goes
  to every stream the event declares.
- **Logging a value you have not thought about.** The allow-list decides which
  stream a field reaches, not whether it should have been logged in the first
  place.

## Not covered here

Serving the application. The example has no `uvicorn` entry point because the
library has nothing to say about one; `create_app()` returns an ordinary
`FastAPI` instance and you serve it however you already do.
