# ADR 0003: Reconstruct Threads From Indexed Relationship Metadata

## Status

Accepted

## Context

The CLI needs useful per-message conversation retrieval while preserving the
PST as read-only and avoiding quote-stripped body text as a source of message
relationships. PSTs expose Internet Message-ID, In-Reply-To, References,
conversation topic, and conversation index inconsistently. Header links can
point outside the archive or be malformed, while broad topic matching can join
unrelated conversations.

## Decision

Persist the available relationship metadata in the disposable SQLite cache and
reconstruct each requested thread from that cache without reopening the PST.

Build a connected component from normalized Internet Message-ID,
In-Reply-To, and References values first. If the component contains only the
requested message, match messages with the same valid conversation-index root.
If that also yields only the requested message, match an exact,
case-insensitive nonempty conversation topic. Return separate cleaned message
records in deterministic chronological order.

## Consequences

The command provides useful partial threads when headers reference messages
outside the archive or relationship data is missing. Topic metadata is a
last-resort fallback and is never unioned with a stronger component, avoiding
known over-grouping of generic subjects.

The initial implementation loads lightweight relationship metadata and builds
the component in Python. This keeps the cache schema simple, but scans the
indexed store for each query. A future performance phase may add normalized
relation tables and indexes without changing the command contract or fallback
order.

## References

- `TASK-001.07`
- `PST Search CLI — Implementation Brief.md`
