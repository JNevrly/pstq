---
id: TASK-001.07
title: Add thread reconstruction command
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
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Store usable message relationship metadata and provide chronological per-message thread retrieval independent of quote stripping.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Importer persists available Internet Message-ID, In-Reply-To, References, conversation topic, and conversation index values
- [ ] #2 thread accepts a stable message ID and returns related indexed messages in deterministic chronological order
- [ ] #3 Thread retrieval displays individual message contributions and does not concatenate repeated quoted bodies
- [ ] #4 Missing or malformed relationship metadata produces a useful partial thread rather than failing the command
- [ ] #5 Tests cover header-based relations, conversation fallback, ordering, and missing data
<!-- AC:END -->
