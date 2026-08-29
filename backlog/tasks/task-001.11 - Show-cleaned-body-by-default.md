---
id: TASK-001.11
title: Show cleaned body by default
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 09:07'
updated_date: '2026-08-29 09:11'
labels: []
dependencies: []
modified_files:
  - pstq/index.py
  - pstq/cli.py
  - tests/test_index.py
  - tests/test_pstq.py
  - README.md
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: medium
type: enhancement
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make show agent-oriented by returning the already persisted cleaned body by default. Add --full to retrieve the original raw body when full message context is necessary. Apply the body selection consistently to human-readable and JSON output.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Default show output returns the cleaned body in both human-readable and JSON modes
- [x] #2 show --full returns the raw body in both human-readable and JSON modes
- [x] #3 The retrieval API selects the cleaned body by default and raw body when requested without changing message metadata
- [x] #4 Tests cover default and full body selection, including CLI JSON output
- [x] #5 README and implementation brief document the show --full contract
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add an explicit full-body selector to persisted message retrieval.
2. Pass --full through the show command for text and JSON output.
3. Cover API and CLI behavior, then document the contract.
4. Verify the suite and configured CLI behavior.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented `get_message(..., full=False)` to return persisted `body_clean` by default and `body_raw` with `full=True`. `show --full` passes that selector through for both text and JSON output. No schema change or reindex is required because both values already exist in the cache.

Validation passed: `uv run tox` completed ruff, formatting, mypy, 81 tests, and 100% coverage. `.venv/bin/pstq --config test_config.yaml show --help` exposes --full, and the same command with an indexed message ID, --full, and --json returned the raw persisted body. The cleaner is intentionally conservative, so --full and default output can be identical when no quote marker is recognized, including currently unrecognized HTML reply structures.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Changed show retrieval to return body_clean by default and body_raw with --full in both text and JSON output. Documented the option in README and the implementation brief. Verified with `uv run tox` (81 tests, 100% coverage) and the configured CLI help plus an indexed --full JSON retrieval. No schema migration or reindex is required because both body fields are already stored.
<!-- SECTION:FINAL_SUMMARY:END -->
