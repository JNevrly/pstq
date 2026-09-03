---
id: TASK-014
title: Add pagination for message search
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-02 10:57'
updated_date: '2026-09-02 18:59'
labels: []
dependencies:
  - TASK-015
references:
  - README.md
  - pstq/cli.py
  - pstq/index.py
priority: medium
type: feature
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Allow callers to traverse complete message-search result sets instead of being limited to a single bounded response of at most 100 records. Pagination must work consistently for full-text and filter-only searches while retaining bounded individual responses suitable for agents.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The search CLI provides a documented way to request subsequent pages while keeping each response bounded
- [x] #2 Callers can traverse every result matching a stable search without duplicates or omissions
- [x] #3 Pagination works for full-text searches and structured filter-only searches
- [x] #4 Result ordering is deterministic across page requests, including ties
- [x] #5 Invalid pagination inputs fail with a clear invalid-request error
- [x] #6 Existing single-page search usage remains supported
- [x] #7 CLI help, README examples, JSON contract documentation, and automated tests cover initial, intermediate, and final pages
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a zero-based --offset option to the search CLI while preserving the existing 1-100 --limit bound and error contract.
2. Thread the offset through search_messages and apply SQLite LIMIT/OFFSET to both deterministic full-text and filter-only orderings.
3. Add index and CLI coverage for initial, intermediate, final, filter-only, ordering, and invalid pagination requests.
4. Document pagination in CLI help, README examples, and the JSON result contract; run focused tests and the full quality suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: TASK-015 is complete and adds deterministic filter-only ordering. Existing full-text ordering is bm25(search_fts) then stable selector; filter-only ordering is date descending then selector. Both paths already enforce a bounded LIMIT but expose no way to request later results. A zero-based offset can be passed through each existing query without a schema migration or response-shape change.

Implemented --offset as a zero-based Click IntRange and threaded it into both SQLite search queries as LIMIT/OFFSET. Tests use five tied records with two-result pages at offsets 0, 2, and 4, verifying no duplicates or omissions, stable selector tie-breaking, and a final short page for full-text and filter-only searches. Validation passed: uv run tox (Ruff lint/format, mypy, 147 pytest cases, 100% coverage).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented zero-based --offset pagination for bounded search responses. Full-text and filter-only queries retain their deterministic orderings and now use SQLite LIMIT/OFFSET; negative offsets return the standard invalid-request error. Documented CLI and README pagination behavior and added coverage for initial, intermediate, final, tied, filter-only, invalid, and legacy single-page requests. Verified with uv run tox: Ruff lint/format, mypy, 147 tests, and 100% coverage. No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->
