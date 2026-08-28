---
id: TASK-001.09
title: Finalize agent CLI contract and documentation
status: To Do
assignee: []
created_date: '2026-08-28 07:21'
labels: []
dependencies:
  - TASK-001.05
  - TASK-001.06
  - TASK-001.07
  - TASK-001.08
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Finalize the configured single-PST CLI interface, deterministic JSON schemas, error handling, limits, and operator documentation for AI-agent use.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Configuration documents one PST path, SQLite index path, and explicit data-directory behavior through Onacol
- [ ] #2 All agent-facing commands have documented JSON schemas, stable IDs, bounded defaults, and consistent exit codes
- [ ] #3 Errors are machine-readable in JSON mode and do not expose stack traces by default
- [ ] #4 The CLI documents read-only PST guarantees, synchronization behavior, locking, and known libpff limitations
- [ ] #5 Integration tests cover the documented command workflows and human-readable output remains usable
<!-- AC:END -->
