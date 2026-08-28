---
id: TASK-001.02
title: Benchmark PST metadata traversal and snapshots
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
updated_date: '2026-08-28 08:05'
labels: []
dependencies:
  - TASK-001.01
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: high
type: spike
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Validate the real PST and pypff assumptions before building the cache. Provide inspect output plus durable metadata snapshots that can be compared across an Outlook update cycle.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 pstq inspect PATH reports libpff version, PST size, store UID, folder count, message count, duration, throughput, scan errors, and bounded sample messages
- [ ] #2 Inspect supports deterministic JSON output
- [ ] #3 A snapshot stores folder path/NID and message NID/folder NID/modification time without reading bodies or attachments
- [ ] #4 A comparison reports new, missing, modified, moved, unchanged, and suspicious identity cases
- [ ] #5 A real mounted PST is benchmarked and findings are recorded in this task before it enters review
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed sample archive for local Phase 1 validation: `temp/test.pst` (2,431,607,808 bytes at discovery). It is a local binary input, not a committed test fixture. Use it for `pstq inspect`, metadata snapshots, and before/after Outlook-update comparison; CI must continue to use fakes and must not require this file.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-28 08:05
---
A sample PST archive has been copied to `temp/test.pst` for local validation.
---
<!-- COMMENTS:END -->
