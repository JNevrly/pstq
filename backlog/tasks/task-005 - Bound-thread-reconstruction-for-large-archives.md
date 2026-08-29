---
id: TASK-005
title: Bound thread reconstruction for large archives
status: To Do
assignee: []
created_date: '2026-08-29 15:25'
labels:
  - code-review
  - performance
dependencies:
  - TASK-001.07
references:
  - docs/adr/0003-reconstruct-threads-from-indexed-relationship-metadata.md
priority: medium
type: enhancement
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`get_thread` reconstructs a conversation by first loading the relationship
metadata for *every* message in the store:

```sql
SELECT nid, internet_message_id, in_reply_to, references_header,
       conversation_topic, conversation_index
FROM message WHERE store_uid = ?
```

It then builds Message-ID and reference maps and a neighbor graph in Python
across the entire archive on each `thread` invocation. For a large PST (the
sample archive is ~2.4 GB) this is O(total messages) in both time and memory for
every single-thread lookup, and none of the relationship columns are indexed.

Functionally this is correct, but it does not scale. Introduce bounded
reconstruction: index the relationship columns and/or restrict the candidate set
(e.g. by conversation topic / conversation-index root) before building the graph,
so cost scales with thread size rather than archive size. Update ADR-0003 if the
reconstruction strategy changes.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 thread no longer loads every message in the store into memory to resolve one conversation
- [ ] #2 Reconstruction results are unchanged for the existing test fixtures
- [ ] #3 Relationship lookups are backed by appropriate indexes or a bounded candidate query
- [ ] #4 ADR-0003 reflects the final reconstruction approach if it changed
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Profile the current full-store scan against the large sample PST to establish a baseline.
2. Add indexes for the relationship columns used in reconstruction, or gather candidates by topic/conversation root first.
3. Keep the graph walk but seed it from a bounded candidate set rather than the whole store.
4. Confirm identical thread membership on existing fixtures and update ADR-0003.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:END -->
