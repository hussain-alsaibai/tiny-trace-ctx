# tiny-trace-ctx

**W3C Trace Context propagation, stdlib-only.**

The smallest reliable way to round-trip `traceparent` / `tracestate`
across HTTP, AMQP, and gRPC without the OpenTelemetry runtime.

- ~140 LOC of executable code, zero runtime dependencies.
- `secrets.token_hex`-backed id generation (cryptographically random).
- Vendor `tracestate` order is preserved on round-trip (W3C-compliant).
- Case-insensitive header extraction by default.
- Frozen dataclass: `TraceContext` instances are hashable and safe to share.

## Install

```bash
pip install tiny-trace-ctx
```

## Usage

```python
from tiny_trace_ctx import (
    TraceContext, parse_traceparent, format_traceparent,
    propagate, extract, new_child, new_root,
)

# Start a fresh trace.
ctx = new_root(flags=1)  # flags=1 → sampled
print(format_traceparent(ctx))
# 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01

# Add to outgoing HTTP headers.
headers = {}
propagate(ctx, headers)
# headers now has 'traceparent' (and 'tracestate' if ctx.state is non-empty)

# On the receiving side, extract and continue the trace.
incoming = extract(headers)
child = new_child(incoming)
out_headers = {}
propagate(child, out_headers)
```

## API

### `TraceContext`
Frozen dataclass. `trace_id` (32 hex), `span_id` (16 hex), `flags` (0..255),
optional `parent_id` (16 hex), and a list of `(vendor, value)` tuples in
`state`. Validated on construction: rejects all-zero ids, uppercase hex,
invalid flags, malformed vendor entries.

### `new_root(*, flags=0) -> TraceContext`
Returns a fresh context with a new trace id and span id.

### `new_child(parent, *, flags=None) -> TraceContext`
Returns a child context: same `trace_id` as the parent, a fresh `span_id`,
`parent_id` set to the parent's `span_id`. The parent's `flags` carry
through unless overridden.

### `parse_traceparent(value: str) -> TraceContext`
Parses a `traceparent` value: exactly four `-`-separated fields
(version, trace-id, span-id, flags). Per the W3C spec, `tracestate` is a
separate header and never travels inside `traceparent`, so a value with
an appended fragment is a malformed traceparent. Raises
`TraceContextError` on malformed input.

### `format_traceparent(ctx) -> str`
Returns the `traceparent` wire-format string. Always four fields; it
never carries vendor state.

### `format_tracestate(state) -> str`
Returns the `tracestate` wire-format string: comma-separated
`vendor=value` entries in the order given.

### `propagate(ctx, headers, *, key='traceparent', tracestate_header='tracestate')`
Mutates `headers` in place; returns the dict. Sets the `traceparent`
header, and the `tracestate` header if `ctx.state` is non-empty. Stale
`tracestate` headers are removed when there is no state to propagate.

### `extract(headers, *, key='traceparent', tracestate_header='tracestate', case_insensitive=True)`
Returns a `TraceContext` from a header dict, or `None` if the
`traceparent` header is absent. The vendor state comes from the
`tracestate` header alone, in order.

## Why not just use OTel?

The OTel SDK is 4,000+ LOC. Most teams need only the wire format: parse
a `traceparent`, add it to outgoing requests, correlate logs across
services. tiny-trace-ctx does exactly that in ~140 LOC with zero deps.
It's a great fit when you want the `traceparent` round-trip without
pulling in the full OTel runtime.

## License

MIT.
