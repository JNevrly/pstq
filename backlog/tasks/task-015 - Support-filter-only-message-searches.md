---
id: TASK-015
title: Support filter-only message searches
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-02 10:57'
updated_date: '2026-09-02 11:30'
labels: []
dependencies: []
references:
  - README.md
  - pstq/cli.py
  - pstq/index.py
priority: medium
type: feature
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Allow users to search messages using structured filters without supplying an artificial full-text query. This enables commands such as `pstq search --from "Sender"` for retrieving messages based entirely on sender, recipient, date, folder, or attachment criteria while preserving the existing full-text search behavior when QUERY is supplied.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `pstq search` accepts an omitted QUERY when at least one structured search filter is provided
- [x] #2 A filter-only sender search returns messages matching the existing `--from` semantics without requiring the sender value to be repeated as QUERY
- [x] #3 Filter-only searches support `--from`, `--from-owner`, `--to`, `--after`, `--before`, `--folder`, and `--has-attachment` in compatible combinations
- [x] #4 A search with neither QUERY nor any structured filter fails with a clear invalid-request error
- [x] #5 Text-query searches retain their current FTS5 matching and ranking behavior
- [x] #6 Filter-only results use a documented deterministic ordering
- [x] #7 CLI help, README examples, and automated tests document and verify filter-only searches
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Make QUERY optional in the search CLI while rejecting requests with neither text nor a structured filter before synchronization.
2. Extend search_messages with a filter-only SQLite projection query ordered by date descending and stable selector; retain the existing FTS query and ranking path for text queries.
3. Add CLI and index coverage for filter-only searches, error handling, deterministic ordering, and unchanged FTS behavior.
4. Update CLI help and README examples, then run focused tests and the project quality suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: search requires a positional Click QUERY and index.search_messages rejects blank queries before constructing an FTS-only statement. Structured fields already live in search_document, so a filter-only query can avoid search_fts entirely without a schema change.

Implemented optional CLI QUERY validation before synchronization. Filter-only searches read search_document directly, return empty snippets with score 0.0, and order by date descending then selector; text searches retain the prior FTS5 statement and bm25 ordering. Added CLI/index tests for sender, owner aliases, compatible filters, validation, ordering, and FTS regression. Full uv run tox passed (ruff, formatting, mypy, 145 tests, 100% coverage).
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-09-02 11:30
---
Human: Running `pstq --config test_config.yaml search --from "Florian"` returned `Error: Missing argument 'QUERY'.`
---

author: @opencode
created: 2026-09-02 11:30
---
Agent: The exact command succeeds with the workspace build as `uv run pstq --config test_config.yaml search --from Florian`; no plain `pstq` executable is installed here. The reported behavior is consistent with an older installed package or a different environment.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented optional search QUERY support for structured filter-only requests. Filter-only queries read the normalized search projection, preserve all existing structured filter semantics, return score 0.0 with empty snippets, and order deterministically by descending date then selector. Requests without text or filters now return invalid_request before synchronization; text queries retain the original FTS5 and bm25 path. Updated CLI help and README examples. Verified with uv run tox: Ruff lint/format, mypy, 145 pytest cases, and 100% coverage all passed. No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->
