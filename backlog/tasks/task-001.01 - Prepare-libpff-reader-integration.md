---
id: TASK-001.01
title: Prepare libpff reader integration
status: To Do
assignee: []
created_date: '2026-08-28 07:20'
labels: []
dependencies: []
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: high
type: task
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make the devcontainer reproducibly build and install a pinned libpff/pypff revision for Python 3.13. Add a narrow read-only PST adapter boundary that converts supported pypff objects into project-owned records and permits fakes in tests.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The devcontainer builds and imports a pinned pypff revision with Python 3.13
- [ ] #2 The adapter opens PST files read-only and reports actionable errors for missing or unreadable files
- [ ] #3 The adapter retrieves and normalizes the message-store PidTagRecordKey as the store UID
- [ ] #4 The adapter exposes folder/message traversal, NIDs, modification times, and available mail properties needed by later tasks
- [ ] #5 Tests cover adapter behavior with fakes and do not require a real PST in CI
<!-- AC:END -->
