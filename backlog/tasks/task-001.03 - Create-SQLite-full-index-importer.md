---
id: TASK-001.03
title: Create SQLite full-index importer
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
labels: []
dependencies:
  - TASK-001.02
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: high
type: task
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create the disposable SQLite cache and its first full importer from the normalized PST reader. Persist enough normalized mail data for later retrieval without reopening the PST.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Schema stores one PST store, folders, messages, recipients, and attachment metadata using store UID plus NID uniqueness
- [ ] #2 Messages preserve a selected raw body plus its source format and parsed relationship metadata where available
- [ ] #3 A full import is transactional and leaves the prior usable index intact on failure
- [ ] #4 Deleting the SQLite database followed by a full import recreates equivalent indexed records from the PST
- [ ] #5 Schema and importer tests cover representative normalized records without requiring a real PST
<!-- AC:END -->
