---
id: TASK-001.04
title: Implement atomic incremental synchronization
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
labels: []
dependencies:
  - TASK-001.03
references:
  - PST Search CLI — Implementation Brief.md
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
- [ ] #1 Index state records source path, size, mtime_ns, store UID, schema version, and last successful synchronization
- [ ] #2 Unchanged PST metadata skips scanning and search can use the existing index immediately
- [ ] #3 Changed messages are re-read, same-NID folder moves update only folder relationships, and unobserved messages are removed after a successful full scan
- [ ] #4 Synchronization aborts without changing the usable index if traversal fails or pre/post PST metadata differs
- [ ] #5 Full synchronization remains available as a recovery path
- [ ] #6 Tests cover new, changed, moved, deleted, unchanged, interrupted, and source-changed-during-scan cases
<!-- AC:END -->
