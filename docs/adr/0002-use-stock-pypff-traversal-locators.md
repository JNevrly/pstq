# ADR 0002: Use Stock pypff Traversal Locators

## Status

Accepted

## Context

libpff 20231205 provides direct item lookup in its C API, but stock pypff does
not expose it. Attachment extraction needs to reopen a PST and reach one
message without an archive-wide traversal. Adding a local pypff binding patch
made the otherwise reproducible native installation harder to maintain.

## Decision

During indexing, persist each folder's child index and every message's index
within its folder. To extract an attachment, synchronize the cache first, then
use stock pypff `get_sub_folder()` calls from the root and one
`get_sub_message()` call. Validate that the reached message identifier matches
the requested NID before reading attachment bytes.

## Consequences

The devcontainer builds the checksum-verified upstream libpff-python source
unchanged. Extraction is bounded by folder depth and does not scan the archive.
Locators are valid only for the indexed source state, so extraction must
synchronize first and must reject a mismatched message identifier.

## References

- `TASK-001.08`
- `docs/adr/0001-expose-direct-pst-item-lookup.md`
