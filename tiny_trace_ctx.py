"""tiny_trace_ctx — stdlib-only W3C Trace Context propagation.

The smallest reliable way to round-trip W3C Trace Context
(`traceparent` + `tracestate`) across HTTP, AMQP, and gRPC without
the OpenTelemetry runtime. Pure Python standard library — no
`opentelemetry-*` dependency, no async loop hijack, no surprises.

Why?
----
W3C Trace Context is the inter-service standard for propagating
trace identifiers. Most teams only need it for log correlation
across services, and adopting the full OTel runtime for that is
4,000+ LOC of overhead. tiny_trace_ctx does just the wire format
and the propagation round-trip, in ~140 LOC.

Public API
----------
- `TraceContext` — the dataclass carrying trace_id, span_id, flags,
  optional parent_id, and the vendor `tracestate` list.
- `parse_traceparent(header)` — parse a `traceparent` header value.
- `format_traceparent(ctx)` — emit the wire format for `traceparent`.
- `format_tracestate(state)` — emit the wire format for `tracestate`.
- `propagate(ctx, headers, key='traceparent')` — add the headers to a
  dict (mutates in place; returns the dict).
- `extract(headers, *, key='traceparent')` — return a TraceContext
  from a header dict, or None if absent.
- `new_child(parent, *, flags=0)` — start a fresh context whose
  trace_id matches the parent and whose span_id is freshly generated
  (matches the W3C "child span" semantics).
- `new_root(*, flags=0)` — start a brand-new trace.
- `random_trace_id()`, `random_span_id()` — 16-byte and 8-byte hex
  generators using `secrets.token_hex`.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Iterable, Mapping


__version__ = "0.1.0"


# ---------- Constants ----------

TRACEPARENT_VERSION = "00"
VALID_FLAGS = 0xFF  # 8-bit field

# Regex from the W3C Trace Context spec (section 3.2).
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})"
    r"-(?P<trace_id>[0-9a-f]{32})"
    r"-(?P<span_id>[0-9a-f]{16})"
    r"-(?P<flags>[0-9a-f]{2})$"
)

_TRACESTATE_ENTRY_RE = re.compile(
    r"^(?P<vendor>[a-z][a-z0-9_\-*/]{0,255})"
    r"=(?P<value>[ !#\$%&'*+\-.^_|~0-9a-zA-Z]{1,256})$"
)


# ---------- Errors ----------


class TraceContextError(ValueError):
    """Raised when a `traceparent` / `tracestate` value is malformed."""


# ---------- Helpers ----------


def random_trace_id() -> str:
    """Return a fresh 16-byte trace id, lowercase hex (32 chars)."""
    return secrets.token_hex(16)


def random_span_id() -> str:
    """Return a fresh 8-byte span id, lowercase hex (16 chars)."""
    return secrets.token_hex(8)


def _is_zero(s: str) -> bool:
    return all(c == "0" for c in s)


# ---------- Dataclass ----------


@dataclass(frozen=True)
class TraceContext:
    """A W3C Trace Context.

    Attributes
    ----------
    trace_id: 32 lowercase-hex chars (16 bytes). All-zero is invalid.
    span_id: 16 lowercase-hex chars (8 bytes). All-zero is invalid.
    flags: 8-bit int. Bit 0 (0x01) is the "sampled" flag.
    parent_id: optional 16-hex parent span id (if this context was
        extracted from a header that carried a parent).
    state: ordered list of `(vendor, value)` tuples from the
        `tracestate` header. Order is preserved on round-trip.
    """

    trace_id: str
    span_id: str
    flags: int = 0
    parent_id: str | None = None
    state: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", self.trace_id or ""):
            raise TraceContextError(
                f"trace_id must be 32 lowercase hex chars, got {self.trace_id!r}"
            )
        if _is_zero(self.trace_id):
            raise TraceContextError("trace_id must not be all zeros")
        if not re.fullmatch(r"[0-9a-f]{16}", self.span_id or ""):
            raise TraceContextError(
                f"span_id must be 16 lowercase hex chars, got {self.span_id!r}"
            )
        if _is_zero(self.span_id):
            raise TraceContextError("span_id must not be all zeros")
        if not 0 <= int(self.flags) <= VALID_FLAGS:
            raise TraceContextError(
                f"flags must fit in 8 bits (0..{VALID_FLAGS}), got {self.flags!r}"
            )
        if self.parent_id is not None and not re.fullmatch(
            r"[0-9a-f]{16}", self.parent_id
        ):
            raise TraceContextError(
                f"parent_id must be 16 lowercase hex chars, got {self.parent_id!r}"
            )
        for vendor, value in self.state:
            if not _TRACESTATE_ENTRY_RE.match(f"{vendor}={value}"):
                raise TraceContextError(f"invalid tracestate entry: {vendor}={value!r}")

    @property
    def sampled(self) -> bool:
        return bool(self.flags & 0x01)

    def with_sampled(self, sampled: bool) -> "TraceContext":
        """Return a copy with the `sampled` flag updated."""
        new_flags = (self.flags & ~0x01) | (0x01 if sampled else 0x00)
        return TraceContext(
            trace_id=self.trace_id,
            span_id=self.span_id,
            flags=new_flags,
            parent_id=self.parent_id,
            state=list(self.state),
        )

    def with_state(self, state: list[tuple[str, str]]) -> "TraceContext":
        return TraceContext(
            trace_id=self.trace_id,
            span_id=self.span_id,
            flags=self.flags,
            parent_id=self.parent_id,
            state=list(state),
        )


# ---------- Parse / format ----------


def parse_traceparent(value: str) -> TraceContext:
    """Parse a `traceparent` header value.

    Per the W3C spec, `traceparent` is exactly four `-`-separated
    fields: version, trace-id, parent-id, and flags. `tracestate` is a
    separate header and is never carried inside `traceparent`.

    Raises `TraceContextError` on malformed input.
    """
    if value is None:
        raise TraceContextError("traceparent is None")
    s = str(value).strip()
    if not s:
        raise TraceContextError("traceparent is empty")
    m = _TRACEPARENT_RE.match(s)
    if not m:
        raise TraceContextError(f"malformed traceparent: {s!r}")
    version = m.group("version")
    if version != TRACEPARENT_VERSION:
        raise TraceContextError(
            f"unsupported traceparent version: {version!r} "
            f"(supported: {TRACEPARENT_VERSION!r})"
        )
    trace_id = m.group("trace_id")
    span_id = m.group("span_id")
    if _is_zero(trace_id) or _is_zero(span_id):
        raise TraceContextError(
            "traceparent has all-zero trace_id or span_id (invalid)"
        )
    flags = int(m.group("flags"), 16)
    return TraceContext(
        trace_id=trace_id,
        span_id=span_id,
        flags=flags,
    )


def format_traceparent(
    ctx: TraceContext,
) -> str:
    """Format a `traceparent` header value.

    The result is always exactly four `-`-separated fields. Vendor
    `tracestate` lives in its own header; use `format_tracestate`.
    """
    if not isinstance(ctx, TraceContext):
        raise TypeError(f"expected TraceContext, got {type(ctx).__name__}")
    return f"{TRACEPARENT_VERSION}-{ctx.trace_id}-{ctx.span_id}-{ctx.flags:02x}"


def format_tracestate(state: Iterable[tuple[str, str]] | None) -> str:
    """Format a `tracestate` header value.

    Entries are comma-separated in the order given. Returns an empty
    string when there is no state.
    """
    if state is None:
        return ""
    return ",".join(f"{vendor}={value}" for vendor, value in state)


# ---------- Propagation ----------


def propagate(
    ctx: TraceContext,
    headers: dict,
    *,
    key: str = "traceparent",
    tracestate_header: str = "tracestate",
) -> dict:
    """Add `traceparent` (and optional `tracestate`) to a header dict.

    Mutates `headers` in place and returns it. If `ctx.state` is
    non-empty, the `tracestate` header is also set. Stale tracestate
    headers are removed when we have no state to propagate.
    """
    if not isinstance(ctx, TraceContext):
        raise TypeError(f"expected TraceContext, got {type(ctx).__name__}")
    if not isinstance(headers, dict):
        raise TypeError(f"headers must be a dict, got {type(headers).__name__}")
    headers[key] = format_traceparent(ctx)
    if ctx.state:
        headers[tracestate_header] = format_tracestate(ctx.state)
    elif tracestate_header in headers:
        del headers[tracestate_header]
    return headers


def _parse_tracestate(raw: str) -> list[tuple[str, str]]:
    """Parse a `tracestate` header value into ordered (vendor, value).

    Raises `TraceContextError` on a malformed entry.
    """
    entries: list[tuple[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise TraceContextError(f"invalid tracestate entry: {item!r}")
        vendor, _, value = item.partition("=")
        vendor = vendor.strip()
        value = value.strip()
        if not _TRACESTATE_ENTRY_RE.match(f"{vendor}={value}"):
            raise TraceContextError(f"invalid tracestate entry: {item!r}")
        entries.append((vendor, value))
    return entries


def extract(
    headers: Mapping[str, str],
    *,
    key: str = "traceparent",
    tracestate_header: str = "tracestate",
    case_insensitive: bool = True,
) -> TraceContext | None:
    """Return a `TraceContext` from a header dict, or None if absent.

    If `tracestate_header` is present, its entries are appended to the
    returned context's `state`. `case_insensitive=True` matches HTTP
    header semantics; pass False to require an exact-case key.
    """
    if headers is None:
        return None
    if case_insensitive:
        lower = {k.lower(): v for k, v in headers.items()}
        k = key.lower()
        ts = tracestate_header.lower()
        if k not in lower:
            return None
        ctx = parse_traceparent(lower[k])
        vendor_entries = _parse_tracestate(lower.get(ts, ""))
        return ctx.with_state(vendor_entries)
    if key not in headers:
        return None
    ctx = parse_traceparent(headers[key])
    if tracestate_header in headers:
        return ctx.with_state(_parse_tracestate(headers[tracestate_header]))
    return ctx


# ---------- Span helpers ----------


def new_child(parent: TraceContext, *, flags: int | None = None) -> TraceContext:
    """Start a child span for the given parent.

    The returned context shares the parent's `trace_id` (so logs
    correlate) and uses a freshly-generated `span_id`. The
    `parent_id` is set to the parent's `span_id` for downstream
    inspection.
    """
    return TraceContext(
        trace_id=parent.trace_id,
        span_id=random_span_id(),
        flags=parent.flags if flags is None else flags,
        parent_id=parent.span_id,
        state=list(parent.state),
    )


def new_root(*, flags: int = 0) -> TraceContext:
    """Start a fresh root span with a new trace id and span id."""
    return TraceContext(
        trace_id=random_trace_id(),
        span_id=random_span_id(),
        flags=flags,
    )


__all__ = [
    "TRACEPARENT_VERSION",
    "TraceContext",
    "TraceContextError",
    "extract",
    "format_traceparent",
    "new_child",
    "new_root",
    "parse_traceparent",
    "propagate",
    "random_span_id",
    "random_trace_id",
]
