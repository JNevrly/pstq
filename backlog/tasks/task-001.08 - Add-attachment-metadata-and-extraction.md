---
id: TASK-001.08
title: Add attachment metadata and extraction
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
labels: []
dependencies:
  - TASK-001.01
  - TASK-001.03
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Expose attachment metadata from the cache and extract original attachment bytes from the PST on demand without storing binary copies in SQLite.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Importer stores attachment filename, MIME type where available, size, index within message, and message relationship
- [ ] #2 attachments lists persisted metadata for a stable message ID without reopening the PST
- [ ] #3 attachment writes the requested original bytes to an explicitly supplied output path
- [ ] #4 PST item lookup is direct by NID; extraction never scans every folder/message to find one attachment
- [ ] #5 The required pypff binding extension is pinned, tested, and documented until accepted upstream
- [ ] #6 Tests cover metadata, invalid identifiers, output safety, and direct lookup abstraction
<!-- AC:END -->
