# ADR 0001: Expose Direct PST Item Lookup

## Status

Superseded by [ADR 0002](0002-use-stock-pypff-traversal-locators.md)

## Context

Attachment extraction must retrieve one message by its PST NID without walking
every folder and message. libpff 20231205 exposes
`libpff_file_get_item_by_identifier`, but its pypff binding does not expose
that function. The project pins this source release and builds its wheel in the
devcontainer.

## Decision

Initially, the project added `pypff.file.get_item_by_identifier(item_identifier)`
through a local source patch. This decision is superseded because the patch
adds native-build maintenance for one operation.

## Consequences

The local patch is removed. Attachment extraction now uses the persisted
stock-pypff traversal locator specified by ADR 0002.

## References

- `TASK-001.08`
- `docs/adr/0002-use-stock-pypff-traversal-locators.md`
