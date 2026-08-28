---
id: TASK-001
title: Build offline PST query CLI
status: To Do
assignee: []
created_date: '2026-08-28 07:20'
labels: []
dependencies: []
references:
  - PST Search CLI — Implementation Brief.md
priority: high
type: feature
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Deliver a read-only Linux CLI that indexes one configured Outlook PST into a disposable SQLite/FTS5 cache and provides deterministic JSON retrieval for AI agents. The PST remains authoritative; normal searches block to synchronize the cache when the PST changed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A configured PST can be inspected, indexed, searched, and retrieved without modifying the PST
- [ ] #2 The SQLite index is disposable and can be rebuilt from the PST
- [ ] #3 The initial release supports one configured PST while retaining store-aware identities in storage
- [ ] #4 Agent-facing commands produce deterministic JSON and return bounded result sets
<!-- AC:END -->
