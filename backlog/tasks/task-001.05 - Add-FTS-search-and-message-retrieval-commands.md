---
id: TASK-001.05
title: Add FTS search and message retrieval commands
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
labels: []
dependencies:
  - TASK-001.04
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: high
type: task
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add the primary agent workflow: status, folders, lexical search, and message display from SQLite. Search must synchronize first when the configured PST changed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 status reports index freshness and source/index metadata
- [ ] #2 folders returns stable folder paths and identifiers
- [ ] #3 search blocks for synchronization when required and searches FTS5 with bounded results
- [ ] #4 Search supports query, sender, recipient, date range, folder, attachment, limit, and JSON options
- [ ] #5 Search results omit full bodies and include stable ID, date, participants, subject, folder, snippet, and score
- [ ] #6 show retrieves the complete persisted message from SQLite without opening an unchanged PST
- [ ] #7 Tests cover SQL filtering, FTS query handling, JSON output, and automatic freshness behavior
<!-- AC:END -->
