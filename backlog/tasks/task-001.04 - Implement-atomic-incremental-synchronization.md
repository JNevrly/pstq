---
id: TASK-001.04
title: Implement atomic incremental synchronization
status: Done
assignee: []
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 06:01'
labels: []
dependencies:
  - TASK-001.03
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - pstq/index.py
  - pstq/pst.py
  - tests/test_index.py
  - tests/test_pst.py
parent_task_id: TASK-001
priority: high
type: task
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Synchronize the cache after a PST change using complete metadata scans. Detect new, modified, moved, unchanged, and missing records without reading unchanged message bodies.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Index state records source path, size, mtime_ns, store UID, schema version, and last successful synchronization
- [x] #2 Unchanged PST metadata skips scanning and search can use the existing index immediately
- [x] #3 Changed messages are re-read, same-NID folder moves update only folder relationships, and unobserved messages are removed after a successful full scan
- [x] #4 Synchronization aborts without changing the usable index if traversal fails or pre/post PST metadata differs
- [x] #5 Full synchronization remains available as a recovery path
- [x] #6 Tests cover new, changed, moved, deleted, unchanged, interrupted, and source-changed-during-scan cases
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add versioned source state and source-stability checks to the SQLite cache.
2. Extend PST traversal to read bodies only for selected message NIDs.
3. Implement atomic metadata-driven synchronization for unchanged, new, changed, moved, and deleted records, with full rebuild fallback.
4. Cover all synchronization outcomes and run the project checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: `pstq.index.import_pst` already builds a replacement database atomically, but the cache has no source state and supports no incremental updates. `PstReader.walk(include_bodies=False)` already supports body-free metadata traversal; it will be extended with selective body loading for changed/new NIDs.

Implementation: added `index_state` source metadata, schema version, synchronization timestamp, and generation tracking. `sync_pst()` skips unchanged sources, clones the usable cache for atomic incremental updates, reads bodies only for new/modified NIDs, updates moves without body loading, deletes unobserved rows after complete scans, and falls back to a full import for invalid or replacement-store caches. `PstReader.walk()` now supports selective body loading by NID.

Validation: `tox` passed on 2026-08-29: Ruff lint/format, mypy, 60 pytest cases, and 100% coverage. Tests explicitly cover new, modified, moved, deleted, unchanged, interrupted, source-changed, replacement-store, and incomplete body-scan cases.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-29 06:01
---
Human: Reviewed the implementation and approved closing the task.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented atomic incremental cache synchronization. Source state is versioned in SQLite; unchanged PSTs avoid traversal; new and modified messages alone load bodies; moves and deletions are metadata-only; failures or source changes leave the prior cache intact. `sync_pst(..., full=True)` provides recovery rebuilds. Verified by `tox` (60 tests, lint, format, mypy, 100% coverage). No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->
