---
id: TASK-001.16
title: Stop persisting raw message bodies
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-30 18:58'
updated_date: '2026-08-30 19:09'
labels:
  - storage
  - sqlite
  - cli
dependencies: []
references:
  - pstq/index.py
  - pstq/cli.py
  - docs/adr/0002-use-stock-pypff-traversal-locators.md
parent_task_id: TASK-001
priority: medium
type: enhancement
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Remove `message.body_raw` from the disposable SQLite index to reduce storage duplication. The PST is authoritative and is guaranteed to remain available. Native message `show --full` must synchronize as needed and read the currently selected source body directly from the configured PST; preserving an indexed raw-body snapshot is explicitly out of scope.

Keep cleaned/indexed text and derived recovered-message content in SQLite. Default `show`, search, folders, and thread behavior remain cache-only.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The SQLite `message` schema and all persistence/query paths no longer store or read `body_raw`; incompatible existing indexes are rebuilt through the normal schema-version mechanism.
- [x] #2 Native `show --full` synchronizes the configured PST as needed, resolves the selected message through a refreshed traversal locator, validates the store UID and message NID, and returns the current source body using the existing plain-text, HTML, then RTF precedence.
- [x] #3 Native `show --full` fails clearly when the source PST, store, locator, or selected body cannot be retrieved; it does not silently return cleaned content.
- [x] #4 Default `show`, search, folders, and thread continue to read SQLite without opening or synchronizing the PST.
- [x] #5 Recovered quoted-history records retain their persisted derived body; `--full` does not attempt to substitute an enclosing native PST message.
- [x] #6 Tests cover schema rebuild, no raw-body persistence, validated on-demand native body retrieval, changed or moved source messages, unavailable or mismatched sources, and unchanged cache-only command behavior.
- [x] #7 CLI help and README document that `show --full` reads the current body from the configured PST while default `show` reads persisted cleaned content.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Remove `body_raw` from the SQLite schema and update all native-row mappings while retaining selected format and cleaned text.
2. Add a `PstReader` body-retrieval operation that follows cached traversal locators and verifies the reached NID, then expose a source-backed native full-message service after synchronization.
3. Keep cache-only message retrieval for default and recovered records; make CLI `show --full` synchronize and use the source-backed service.
4. Update CLI/README contracts and add regression tests for schema, retrieval, locator refresh/errors, and cache-only behavior.
5. Run focused and full checks, then prepare the task for review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented schema version 12 without `message.body_raw`. Added `PstReader.read_message_body()` using the persisted traversal locator and NID validation, plus `get_full_message()` which synchronizes native selectors, verifies source/store consistency before and after reading, and preserves recovered selector behavior. `show --full` now calls this source-backed API; default show, search, folders, and thread remain cache-only.

Verification: `uv run pytest` (137 passed) and `uv run ruff check pstq tests`.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-30 18:59
---
The PST source is guaranteed to remain available. Returning the current source body for `show --full` is an accepted tradeoff; an indexed raw-body snapshot is not required.
---

author: @opencode
created: 2026-08-30 19:09
---
Ready for human review. The configured `Done` state is the review handoff; human acceptance remains pending.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Removed `message.body_raw` and bumped the cache schema to 12, so stale indexes are atomically rebuilt without raw source-body storage. Added validated on-demand native body retrieval from the synchronized PST and routed `show --full` through it; default show, search, folders, and thread remain cache-only, and recovered records retain their derived bodies.

Verified with `uv run pytest` (138 passed), `uv run ruff check pstq tests`, `git diff --check`, and `uv run pstq show --help`. No ADR or follow-up tasks were created.
<!-- SECTION:FINAL_SUMMARY:END -->
