---
id: TASK-005
title: Bound thread reconstruction for large archives
status: Done
assignee: []
created_date: '2026-08-29 15:25'
updated_date: '2026-08-30 05:57'
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
- [x] #1 thread no longer loads every message in the store into memory to resolve one conversation
- [x] #2 Reconstruction results are unchanged for the existing test fixtures
- [x] #3 Relationship lookups are backed by appropriate indexes or a bounded candidate query
- [x] #4 ADR-0003 reflects the final reconstruction approach if it changed
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the current thread-reconstruction query, schema migrations, fixtures, and ADR-0003.
2. Replace the full-store metadata scan with indexed, bounded candidate lookup while retaining the existing graph semantics.
3. Add or adjust regression tests for thread membership and query scoping.
4. Run the focused suite, update ADR-0003 as needed, and record verification results.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:BEGIN -->

Investigation confirmed `get_thread` fetched all `message` relationship rows for a store and built the graph in Python. Implemented a schema-v10 normalized `message_relation` table and indexed normalized conversation fallback keys; a recursive SQLite query now returns only header-component NIDs before materializing message records. Existing fixture behavior remains covered by the thread tests; the focused and full suites pass.

Final validation: `uv run pytest -q` (129 passed), `uv run ruff check .` (passed), `uv run mypy pstq` (passed), and `git diff --check` (passed). The new trace-based regression test executes a lookup with 100 unrelated messages, confirms the recursive `message_relation` traversal is used, and confirms the former all-store relationship query is not executed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced full-store Python thread graph reconstruction with a schema-v10 normalized and indexed `message_relation` cache plus recursive SQLite component lookup. Indexed normalized conversation-root and topic fallback keys preserve the existing fallback order. Updated ADR-0003 and added regression coverage for relationship storage, indexes, bounded lookup execution, and existing thread fixtures. Verified with 129 pytest tests, Ruff, mypy, and whitespace checks; no known limitations or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->

<!-- SECTION:NOTES:END -->
