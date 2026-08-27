import pytest

from gfmodules.logging.context import (
    ALWAYS_KEEP_FIELDS,
    CLIENT_TRACE_ID_HEADER,
    CORRELATION_ID_HEADER,
    STANDARD_FIELDS,
    UNSET,
    USER_AGENT_HEADER,
    ContextField,
    bind_context,
    collect_context,
    correlation_headers,
    extract_context,
    register_context_fields,
    registered_fields,
    sanitize_free_text,
    sanitize_header_value,
    update_context,
)

TENANT_ID = ContextField(name="tenant_id", header="X-Tenant-Id")


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    register_context_fields(())


class TestRegistration:
    def test_standard_fields_are_registered_by_default(self) -> None:
        assert registered_fields() == STANDARD_FIELDS

    def test_extras_are_appended_after_the_standard_fields(self) -> None:
        register_context_fields((TENANT_ID,))

        assert registered_fields() == (*STANDARD_FIELDS, TENANT_ID)

    def test_registering_replaces_the_previous_extras(self) -> None:
        register_context_fields((TENANT_ID,))
        register_context_fields(())

        assert registered_fields() == STANDARD_FIELDS

    def test_rejects_an_extra_that_shadows_a_standard_field(self) -> None:
        shadowing = ContextField(name="request_id", header="X-Something")
        args = (shadowing,)

        with pytest.raises(ValueError, match="request_id"):
            register_context_fields(args)

    def test_rejects_duplicate_extras(self) -> None:
        args = (TENANT_ID, TENANT_ID)

        with pytest.raises(ValueError, match="tenant_id"):
            register_context_fields(args)


class TestCollectContext:
    def test_is_empty_when_nothing_is_bound(self) -> None:
        assert collect_context() == {}

    def test_omits_fields_left_unset(self) -> None:
        with bind_context({"request_id": "abc", "ip": UNSET}):
            assert collect_context() == {"request_id": "abc"}

    def test_preserves_the_declared_field_order(self) -> None:
        register_context_fields((TENANT_ID,))
        bound = {
            "tenant_id": "t-1",
            "method": "GET",
            "request_id": "abc",
            "endpoint": "/x",
            "ip": "127.0.0.1",
            "client_trace_id": "trace",
            "correlation_id": "corr",
        }

        with bind_context(bound):
            assert list(collect_context()) == [
                "request_id",
                "ip",
                "client_trace_id",
                "correlation_id",
                "endpoint",
                "method",
                "tenant_id",
            ]

    def test_ignores_values_for_fields_that_are_not_registered(self) -> None:
        with bind_context({"request_id": "abc", "tenant_id": "t-1"}):
            assert collect_context() == {"request_id": "abc"}


class TestUpdateContext:
    def test_adds_to_what_is_already_bound(self) -> None:
        register_context_fields((TENANT_ID,))

        with bind_context({"request_id": "abc"}):
            with update_context({"tenant_id": "t-1"}):
                assert collect_context() == {"request_id": "abc", "tenant_id": "t-1"}

    def test_an_undeclared_field_still_reaches_no_record(self) -> None:
        """Like every other value: only declared fields are collected."""
        with bind_context({"request_id": "abc"}):
            with update_context({"undeclared": "x"}):
                assert collect_context() == {"request_id": "abc"}

    def test_overrides_a_value_that_is_already_bound(self) -> None:
        with bind_context({"request_id": "abc"}):
            with update_context({"request_id": "xyz"}):
                assert collect_context()["request_id"] == "xyz"

    def test_the_addition_is_gone_after_the_block(self) -> None:
        with bind_context({"request_id": "abc"}):
            with update_context({"tenant_id": "t-1"}):
                pass
            assert collect_context() == {"request_id": "abc"}

    def test_works_with_nothing_bound_yet(self) -> None:
        with update_context({"request_id": "abc"}):
            assert collect_context() == {"request_id": "abc"}


class TestBindContext:
    def test_restores_the_previous_context_on_exit(self) -> None:
        with bind_context({"request_id": "outer"}):
            with bind_context({"request_id": "inner"}):
                assert collect_context() == {"request_id": "inner"}
            assert collect_context() == {"request_id": "outer"}
        assert collect_context() == {}

    def test_restores_the_previous_context_when_the_body_raises(self) -> None:
        with bind_context({"request_id": "abc"}):
            with pytest.raises(RuntimeError):
                raise RuntimeError("boom")

        assert collect_context() == {}


class TestExtractContext:
    def test_reads_declared_headers_and_sanitizes_them(self) -> None:
        register_context_fields((TENANT_ID,))
        headers = {CLIENT_TRACE_ID_HEADER: "trace/../1", "X-Tenant-Id": "t 1!"}

        extracted = extract_context(headers)

        assert extracted["client_trace_id"] == "trace1"
        assert extracted["tenant_id"] == "t1"

    def test_uses_unset_for_headers_that_are_absent(self) -> None:
        assert extract_context({})["correlation_id"] == UNSET

    def test_reads_the_user_agent_without_mangling_it(self) -> None:
        headers = {USER_AGENT_HEADER: "Mozilla/5.0 (X11; Linux x86_64)"}

        assert extract_context(headers)["user_agent"] == "Mozilla/5.0 (X11; Linux x86_64)"

    def test_a_user_agent_cannot_forge_a_log_line(self) -> None:
        headers = {USER_AGENT_HEADER: "curl/8.0\n2026-01-01 INFO forged"}

        assert extract_context(headers)["user_agent"] == "curl/8.02026-01-01 INFO forged"

    def test_skips_fields_that_have_no_header(self) -> None:
        assert "endpoint" not in extract_context({})

    def test_can_leave_a_declared_field_unsanitized(self) -> None:
        register_context_fields((ContextField(name="raw", header="X-Raw", sanitize=False),))

        assert extract_context({"X-Raw": "a b/c"})["raw"] == "a b/c"

    def test_header_lookup_is_case_insensitive_for_mappings_that_are_not(self) -> None:
        assert extract_context({"x-client-trace-id": "trace"})["client_trace_id"] == "trace"


class TestSanitizeHeaderValue:
    def test_strips_characters_outside_the_safe_set(self) -> None:
        assert sanitize_header_value("ab/c d_1-2") == "abcd_1-2"

    def test_truncates_to_64_characters(self) -> None:
        assert sanitize_header_value("a" * 100) == "a" * 64

    def test_falls_back_to_unset_when_nothing_survives(self) -> None:
        assert sanitize_header_value("///") == UNSET


class TestSanitizeFreeText:
    def test_keeps_the_punctuation_a_user_agent_needs(self) -> None:
        assert sanitize_free_text("Mozilla/5.0 (X11; Linux x86_64)") == "Mozilla/5.0 (X11; Linux x86_64)"

    def test_strips_the_control_characters_that_would_forge_a_line(self) -> None:
        assert sanitize_free_text("a\nb\tc\x00d\x7f") == "abcd"

    def test_truncates_to_256_characters(self) -> None:
        assert sanitize_free_text("a" * 300) == "a" * 256

    def test_falls_back_to_unset_when_nothing_survives(self) -> None:
        assert sanitize_free_text("\n\t") == UNSET


class TestCorrelationHeaders:
    def test_is_empty_when_nothing_is_bound(self) -> None:
        assert correlation_headers() == {}

    def test_propagates_a_bound_correlation_id(self) -> None:
        with bind_context({"correlation_id": "corr-1"}):
            assert correlation_headers() == {CORRELATION_ID_HEADER: "corr-1"}

    def test_propagates_the_client_trace_id_too_so_a_trace_survives_the_hop(self) -> None:
        with bind_context({"correlation_id": "corr-1", "client_trace_id": "trace-1"}):
            assert correlation_headers() == {
                CORRELATION_ID_HEADER: "corr-1",
                CLIENT_TRACE_ID_HEADER: "trace-1",
            }

    def test_omits_whichever_of_the_two_is_unset(self) -> None:
        with bind_context({"client_trace_id": "trace-1"}):
            assert correlation_headers() == {CLIENT_TRACE_ID_HEADER: "trace-1"}


class TestStandardFields:
    def test_the_ip_is_not_read_from_a_header(self) -> None:
        """X-Forwarded-For is caller controlled; the middleware decides whether to trust it."""
        ip = next(field for field in STANDARD_FIELDS if field.name == "ip")

        assert ip.header is None
        assert "ip" not in extract_context({"X-Forwarded-For": "203.0.113.7"})

    def test_the_always_kept_fields_are_the_correlation_metadata(self) -> None:
        assert ALWAYS_KEEP_FIELDS == {"request_id", "ip", "user_agent", "client_trace_id", "correlation_id"}

    def test_the_user_agent_is_read_from_its_header(self) -> None:
        user_agent = next(field for field in STANDARD_FIELDS if field.name == "user_agent")

        assert user_agent.header == USER_AGENT_HEADER
