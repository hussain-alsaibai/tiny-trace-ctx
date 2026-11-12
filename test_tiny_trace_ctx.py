"""Tests for tiny_trace_ctx — W3C Trace Context propagation.

Covers parse, format, propagate, extract, child/root generation, and
end-to-end cross-service round-tripping with tracestate.
"""

from __future__ import annotations

import re

import pytest

from tiny_trace_ctx import (
    TraceContext,
    TraceContextError,
    extract,
    format_traceparent,
    format_tracestate,
    new_child,
    new_root,
    parse_traceparent,
    propagate,
    random_span_id,
    random_trace_id,
)


# ---------- Constants ----------

VALID_TRACE = "0af7651916cd43dd8448eb211c80319c"
VALID_SPAN = "b7ad6b7169203331"
VALID_HEADER = f"00-{VALID_TRACE}-{VALID_SPAN}-01"


# ---------- random_trace_id / random_span_id ----------


def test_random_trace_id_length_and_charset():
    for _ in range(50):
        tid = random_trace_id()
        assert len(tid) == 32
        assert re.fullmatch(r"[0-9a-f]{32}", tid)


def test_random_trace_id_not_zero():
    seen = {random_trace_id() for _ in range(50)}
    assert all(t != "0" * 32 for t in seen)


def test_random_span_id_length_and_charset():
    for _ in range(50):
        sid = random_span_id()
        assert len(sid) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", sid)


def test_random_span_id_unique():
    seen = {random_span_id() for _ in range(100)}
    assert len(seen) == 100


# ---------- TraceContext construction & validation ----------


def test_construct_minimal():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN)
    assert ctx.trace_id == VALID_TRACE
    assert ctx.span_id == VALID_SPAN
    assert ctx.flags == 0
    assert ctx.parent_id is None
    assert ctx.state == []


def test_construct_with_state():
    ctx = TraceContext(
        trace_id=VALID_TRACE,
        span_id=VALID_SPAN,
        flags=1,
        state=[("vendor", "value")],
    )
    assert ctx.state == [("vendor", "value")]


def test_invalid_trace_id_length_raises():
    with pytest.raises(TraceContextError, match="trace_id must be 32"):
        TraceContext(trace_id="abcd", span_id=VALID_SPAN)


def test_invalid_trace_id_uppercase_raises():
    with pytest.raises(TraceContextError, match="trace_id must be 32"):
        TraceContext(trace_id=VALID_TRACE.upper(), span_id=VALID_SPAN)


def test_all_zero_trace_id_raises():
    with pytest.raises(TraceContextError, match="all zero"):
        TraceContext(trace_id="0" * 32, span_id=VALID_SPAN)


def test_invalid_span_id_raises():
    with pytest.raises(TraceContextError, match="span_id must be 16"):
        TraceContext(trace_id=VALID_TRACE, span_id="nope")


def test_all_zero_span_id_raises():
    with pytest.raises(TraceContextError, match="all zero"):
        TraceContext(trace_id=VALID_TRACE, span_id="0" * 16)


def test_invalid_flags_raises():
    with pytest.raises(TraceContextError, match="flags must fit"):
        TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN, flags=256)


def test_invalid_parent_id_raises():
    with pytest.raises(TraceContextError, match="parent_id must be 16"):
        TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN, parent_id="x" * 5)


def test_invalid_tracestate_entry_raises():
    with pytest.raises(TraceContextError, match="invalid tracestate"):
        TraceContext(
            trace_id=VALID_TRACE,
            span_id=VALID_SPAN,
            state=[("InvalidVendor", "value")],
        )


# ---------- sampled property ----------


def test_sampled_default_false():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN)
    assert ctx.sampled is False


def test_sampled_with_flag_set():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN, flags=0x01)
    assert ctx.sampled is True


def test_with_sampled_returns_new_context():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN, flags=0)
    out = ctx.with_sampled(True)
    assert out.sampled is True
    assert ctx.sampled is False
    assert out.trace_id == ctx.trace_id


def test_with_state_returns_new_context():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN)
    out = ctx.with_state([("a", "b")])
    assert out.state == [("a", "b")]
    assert ctx.state == []


# ---------- parse_traceparent ----------


def test_parse_basic():
    ctx = parse_traceparent(VALID_HEADER)
    assert ctx.trace_id == VALID_TRACE
    assert ctx.span_id == VALID_SPAN
    assert ctx.flags == 0x01
    assert ctx.state == []


def test_parse_traceparent_has_exactly_four_fields():
    ctx = parse_traceparent(VALID_HEADER)
    assert ctx.trace_id == VALID_TRACE
    assert ctx.span_id == VALID_SPAN
    assert ctx.flags == 1
    assert ctx.state == []


def test_parse_rejects_inline_tracestate():
    # tracestate is a separate header; it must never appear inside
    # traceparent, so an inline fragment is a malformed traceparent.
    with pytest.raises(TraceContextError, match="malformed traceparent"):
        parse_traceparent(f"{VALID_HEADER},othervendor=somevalue")


def test_parse_with_tracestate_separate_header():
    ctx = parse_traceparent(VALID_HEADER)
    out = ctx.with_state([("vendor1", "v1"), ("vendor2", "v2")])
    assert out.state == [("vendor1", "v1"), ("vendor2", "v2")]


def test_parse_empty_raises():
    with pytest.raises(TraceContextError, match="empty"):
        parse_traceparent("")


def test_parse_none_raises():
    with pytest.raises(TraceContextError, match="None"):
        parse_traceparent(None)


def test_parse_malformed_raises():
    with pytest.raises(TraceContextError, match="malformed"):
        parse_traceparent("not-a-valid-traceparent")


def test_parse_unsupported_version_raises():
    with pytest.raises(TraceContextError, match="unsupported traceparent version"):
        parse_traceparent(f"ff-{VALID_TRACE}-{VALID_SPAN}-01")


def test_parse_all_zero_trace_id_raises():
    with pytest.raises(TraceContextError, match="all-zero"):
        parse_traceparent(f"00-{'0' * 32}-{VALID_SPAN}-01")


def test_parse_all_zero_span_id_raises():
    with pytest.raises(TraceContextError, match="all-zero"):
        parse_traceparent(f"00-{VALID_TRACE}-{'0' * 16}-01")


def test_parse_invalid_tracestate_fragment_raises():
    bad = f"{VALID_HEADER}-invalidfragment"
    with pytest.raises(TraceContextError, match="malformed traceparent"):
        parse_traceparent(bad)


# ---------- format_traceparent ----------


def test_format_basic():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN, flags=0x01)
    out = format_traceparent(ctx)
    assert out == VALID_HEADER


def test_format_traceparent_never_carries_tracestate():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN)
    out = format_traceparent(ctx)
    assert out == f"00-{VALID_TRACE}-{VALID_SPAN}-00"
    assert "," not in out


def test_format_tracestate():
    assert format_tracestate([("a", "b"), ("c", "d")]) == "a=b,c=d"
    assert format_tracestate([]) == ""
    assert format_tracestate(None) == ""


def test_format_traceparent_ignores_context_state():
    ctx = TraceContext(
        trace_id=VALID_TRACE,
        span_id=VALID_SPAN,
        state=[("ignored", "yes")],
    )
    out = format_traceparent(ctx)
    assert out == f"00-{VALID_TRACE}-{VALID_SPAN}-00"


def test_format_non_tracecontext_raises():
    with pytest.raises(TypeError):
        format_traceparent({"trace_id": VALID_TRACE})


# ---------- propagate ----------


def test_propagate_adds_traceparent():
    ctx = new_root(flags=1)
    headers = {}
    out = propagate(ctx, headers)
    assert "traceparent" in headers
    assert out is headers


def test_propagate_adds_tracestate_when_state_present():
    ctx = new_root(flags=1).with_state([("vendor", "value")])
    headers = {}
    propagate(ctx, headers)
    assert "tracestate" in headers
    assert headers["tracestate"] == "vendor=value"


def test_propagate_removes_stale_tracestate():
    headers = {"traceparent": VALID_HEADER, "tracestate": "stale=true"}
    ctx = new_root(flags=1)
    propagate(ctx, headers)
    assert "tracestate" not in headers


def test_propagate_non_dict_raises():
    with pytest.raises(TypeError):
        propagate(new_root(), [])


def test_propagate_non_tracecontext_raises():
    with pytest.raises(TypeError):
        propagate({}, {})


# ---------- extract ----------


def test_extract_returns_none_when_absent():
    assert extract({}) is None
    assert extract({"other": "value"}) is None


def test_extract_round_trip():
    original = new_root(flags=1)
    headers = {}
    propagate(original, headers)
    out = extract(headers)
    assert out is not None
    assert out.trace_id == original.trace_id
    assert out.span_id == original.span_id
    assert out.flags == original.flags


def test_extract_case_insensitive():
    headers = {"TraceParent": VALID_HEADER}
    out = extract(headers)
    assert out is not None
    assert out.trace_id == VALID_TRACE


def test_extract_reads_only_the_tracestate_header():
    headers = {
        "traceparent": VALID_HEADER,
        "tracestate": "separate=ok,other=yes",
    }
    out = extract(headers)
    assert out is not None
    assert out.state == [("separate", "ok"), ("other", "yes")]


def test_extract_does_not_duplicate_state():
    # A header carrying the same vendor in both traceparent and
    # tracestate must yield the vendor exactly once.
    headers = {
        "traceparent": VALID_HEADER,
        "tracestate": "vendor=value",
    }
    out = extract(headers)
    assert out is not None
    assert out.state == [("vendor", "value")]


def test_extract_strips_whitespace_in_tracestate():
    headers = {
        "traceparent": VALID_HEADER,
        "tracestate": "  a=b  ,  c=d  ",
    }
    out = extract(headers)
    assert out is not None
    assert out.state == [("a", "b"), ("c", "d")]


def test_extract_invalid_tracestate_entry_raises():
    headers = {
        "traceparent": VALID_HEADER,
        "tracestate": "InvalidKey=value",
    }
    with pytest.raises(TraceContextError):
        extract(headers)


def test_extract_case_sensitive_strict():
    headers = {"Traceparent": VALID_HEADER}
    assert extract(headers, case_insensitive=False) is None


# ---------- new_child / new_root ----------


def test_new_root_unique_ids():
    ids = {new_root().trace_id for _ in range(20)}
    assert len(ids) == 20


def test_new_root_default_flags_zero():
    ctx = new_root()
    assert ctx.flags == 0
    assert ctx.parent_id is None


def test_new_root_inherits_sampled_flag():
    ctx = new_root(flags=1)
    assert ctx.sampled is True


def test_new_child_inherits_trace_id():
    parent = new_root(flags=1)
    child = new_child(parent)
    assert child.trace_id == parent.trace_id
    assert child.span_id != parent.span_id
    assert child.parent_id == parent.span_id
    assert child.flags == parent.flags


def test_new_child_can_override_flags():
    parent = new_root(flags=1)
    child = new_child(parent, flags=0)
    assert child.sampled is False
    assert child.trace_id == parent.trace_id


def test_new_child_inherits_state():
    parent = new_root(flags=1).with_state([("vendor", "v")])
    child = new_child(parent)
    assert child.state == [("vendor", "v")]


# ---------- end-to-end cross-service round trip ----------


def test_cross_service_propagation_preserves_state_order():
    original = new_root(flags=1).with_state(
        [
            ("vendor-a", "1"),
            ("vendor-b", "2"),
            ("vendor-c", "3"),
        ]
    )
    headers = {}
    propagate(original, headers)
    incoming = extract(headers)
    assert incoming is not None
    assert incoming.state == original.state
    child = new_child(incoming)
    out_headers = {}
    propagate(child, out_headers)
    final = extract(out_headers)
    assert final is not None
    assert final.trace_id == original.trace_id
    # The parent link is established by new_child; the wire format
    # carries only trace-id, span-id and flags, so it cannot survive
    # serialization.
    assert child.parent_id == incoming.span_id
    assert final.parent_id is None
    assert final.state == original.state


def test_flags_byte_2_does_not_break_format():
    ctx = TraceContext(trace_id=VALID_TRACE, span_id=VALID_SPAN, flags=0x03)
    out = format_traceparent(ctx)
    assert out.endswith("-03")
    back = parse_traceparent(out)
    assert back.flags == 0x03
