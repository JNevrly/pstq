---
id: TASK-001.06
title: Clean quoted reply history for indexing
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
labels: []
dependencies:
  - TASK-001.05
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create a replaceable body-cleaning stage that conservatively removes clearly quoted Outlook reply history. Preserve unmodified raw text and reindex cleaned content.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Raw message body and its source format remain unchanged in SQLite
- [ ] #2 Cleaning removes only recognized original-message separators and high-confidence Outlook header blocks
- [ ] #3 Ambiguous content remains searchable
- [ ] #4 Normal FTS indexes cleaned body content instead of raw body content
- [ ] #5 Changing the cleaner version requires and performs a full reindex
- [ ] #6 Tests cover plain-text quoted replies, false-positive protection, and reindexing
<!-- AC:END -->
