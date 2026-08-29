---
id: TASK-001.14
title: Search recovered owner responses
status: To Do
assignee:
  - '@opencode'
created_date: '2026-08-29 16:28'
labels: []
dependencies:
  - TASK-001.13
references:
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Allow agents to search high-confidence recovered owner-authored response and forwarded-context records by content without mixing them into the existing native-message search results.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A dedicated command or explicit search mode returns bounded deterministic results from recovered owner records only
- [ ] #2 Results expose stable recovered IDs, date, sender, subject, relation, source-message provenance, and a content snippet
- [ ] #3 Search respects the configured owner aliases and returns no recovered records when history recovery is disabled
- [ ] #4 Recovered search data is atomically rebuilt and removed with its derived records during full and incremental synchronization
- [ ] #5 Native search behavior and result contract remain unchanged
- [ ] #6 Tests cover FTS matching, result ordering and bounds, provenance, disabled recovery, deduplication, and synchronization cleanup
<!-- AC:END -->
