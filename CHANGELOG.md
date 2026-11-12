# Changelog

All notable changes to `tiny-trace-ctx` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `traceparent` no longer carries inline `tracestate`. The header was
  emitted as `00-<trace>-<span>-01,vendor=value` *and* as a separate
  `tracestate` header, and `extract()` read both, so every vendor came
  back twice and the duplication compounded on each hop of a
  cross-service chain.
- `parse_traceparent()` accepts exactly the four W3C fields. A value
  with an appended fragment is now reported as a malformed traceparent
  instead of a malformed tracestate fragment.
- `extract()` reads vendor state from the `tracestate` header only.

### Added

- `format_tracestate(state)` emits the `tracestate` wire format.

### Changed

- `format_traceparent(ctx)` no longer takes a `tracestate` argument and
  never emits vendor state. Use `format_tracestate()` or
  `propagate()`, which sets the `tracestate` header.
- `parent_id` is not part of the wire format, so it does not survive a
  header round-trip. It is set by `new_child()` and available on the
  in-process context.


## [0.1.0] — 2026-10-07

### Added

- Initial release.
- `TraceContext` frozen dataclass with validation (32-hex trace_id,
  16-hex span_id, 8-bit flags, optional parent_id, ordered vendor state).
- `random_trace_id()` and `random_span_id()` (cryptographically
  random via `secrets.token_hex`).
- `parse_traceparent(value: str) -> TraceContext` with inline
  tracestate support.
- `format_traceparent(ctx, *, tracestate=None) -> str` for the
  W3C wire format.
- `propagate(ctx, headers, ...)` and `extract(headers, ...)` for
  HTTP-style header round-tripping (case-insensitive by default).
- `new_root(*, flags=0)` and `new_child(parent, *, flags=None)`
  for span helpers.
- 47 tests covering parse, format, propagate, extract, child/root
  generation, end-to-end cross-service round-tripping with tracestate,
  and validation edge cases.
