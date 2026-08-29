# ADR 0005: Unify Native and Recovered Message Search

## Status

Accepted

## Context

Recovered owner-authored messages are derived from quote history and require
separate storage for provenance, deduplication, and synchronization. Exposing
that implementation detail through a separate command and result fields makes
agents use different workflows for semantically equivalent mail.

## Decision

Keep the derived tables from ADR 0004, but materialize native and recovered
messages into one disposable search-document projection and one FTS5 corpus.
The normal `search` command ranks both document kinds together and returns the
existing ordinary message result schema. `show` and `thread` likewise return
ordinary message-shaped records for either stable selector. Recovery relation
and source provenance remain internal data and are never emitted by the CLI.

Each recovered document uses the occurrence with the lowest native source
message NID and quote position as its canonical source. Its folder is the
canonical source folder, and it never advertises attachments. Existing
`STORE_UID:q:HASH` selectors remain stable. The `--from-owner` search shortcut
OR-matches all configured owner names and email aliases.

## Consequences

FTS scores, limits, and query syntax apply globally instead of per storage
kind. Users need no recovery-specific command or output parsing. Changing
derived data rebuilds its projection atomically with the underlying recovered
records. A recovered item can be shown or used as a thread anchor by resolving
its canonical native source internally.

The canonical-folder rule intentionally selects one deterministic folder when
identical quoted content occurs in more than one source folder. Attachment
metadata is not attributed from that source to the recovered item.

## References

- `TASK-001.14`
- `docs/adr/0004-model-quoted-history-as-derived-messages.md`
