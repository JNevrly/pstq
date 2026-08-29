# ADR 0004: Model Quoted History as Derived Messages

## Status

Accepted

## Context

Manually curated PST archives can omit Sent Items even when replies and
forwards preserve the archive owner's contributions in quoted message history.
Those blocks are not native PST items and can occur repeatedly at multiple
depths. Treating them as native messages would invent NIDs and corrupt the
meaning of the existing `message` table.

## Decision

Keep native PST messages authoritative and store recovered quoted messages in
separate, disposable SQLite tables. A derived record has a deterministic
canonical-content fingerprint and one or more quote occurrences identifying its
native source messages and positions.

Only complete, localized Outlook header blocks are eligible. Recovery is
limited to explicitly configured archive-owner aliases and uses an IANA
timezone for quoted timestamps without offsets. A derived record is suppressed
when its exact canonical sender, normalized subject, and body fingerprint
matches a native indexed message. Recovered records augment a real thread only
through quote-occurrence provenance; they never expand the native metadata
relationship component defined by ADR 0003.

Forwarded blocks are retained as `forwarded_context`, not asserted to be reply
ancestors. The parser is versioned and its settings are part of cache freshness,
so any parser or owner-context change causes an atomic full rebuild.

## Consequences

Thread output can show missing owner contributions without modifying the PST,
duplicating native messages, or changing FTS search semantics. Output exposes
derived identity and source provenance so consumers can distinguish recovered
content from native records.

Recovery deliberately omits incomplete, edited, inline, and unsupported quote
formats rather than guess. The first implementation supports English, Czech,
German, and Japanese Outlook headers; RTF-only structural quote analysis is not
supported. Changing owner aliases or timezone rebuilds the disposable cache.

## References

- `TASK-001.13`
- `docs/adr/0003-reconstruct-threads-from-indexed-relationship-metadata.md`
