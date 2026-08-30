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

Normalize each parsed Internet Message-ID and reference into an indexed
`message_relation` cache table. Resolve the header-connected component with a
recursive SQLite query over those identifiers, materializing only its member
NIDs. Persist normalized conversation-index roots and conversation-topic keys
on `message`, with indexes for each fallback lookup.

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

Thread lookup cost is proportional to the header-connected component or the
selected fallback group, rather than every message in the store. The cache has
additional derived relationship rows and indexes, and a schema-version change
rebuilds disposable existing caches.

## References

- `TASK-001.07`
- `PST Search CLI — Implementation Brief.md`
