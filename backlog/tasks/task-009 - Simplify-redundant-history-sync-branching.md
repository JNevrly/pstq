---
id: TASK-009
title: Simplify redundant history sync branching
status: Done
assignee:
  - '@Josef'
created_date: '2026-08-30 08:30'
updated_date: '2026-08-30 07:20'
labels:
  - code-review
  - cleanup
dependencies: []
priority: low
type: chore
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two small cleanups in `pstq/cli.py`, no behavior change intended:

1. Dead conditional around history-aware sync. Both `search` and `attachment`
   branch on whether the resolved history equals the default:

   ```python
   if history == DEFAULT_HISTORY_SETTINGS:
       sync_pst(source_path, database_path)
   else:
       sync_pst(source_path, database_path, history)
   ```

   `sync_pst` (and `extract_attachment`) already default their `history`
   parameter to `DEFAULT_HISTORY_SETTINGS`, so both branches are equivalent.
   Each pair collapses to a single call that always passes `history`.

2. Function-local import. `_history_settings` imports
   `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` inside the function on
   every invocation. Move it to the module-level imports for consistency with the
   rest of the file.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 search and attachment call the sync/extract helpers once, always passing the resolved history, with no default-equality branch
- [x] #2 zoneinfo is imported at module scope
- [x] #3 No behavior change; the existing suite and static checks pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace each default-equality branch with a single helper call that passes the resolved history.
2. Hoist the zoneinfo import to module scope and update default-history CLI assertions.
3. Run the focused CLI suite, the full test suite, Ruff, and mypy.

4. Reformat tests/test_pstq.py and tests/test_index.py, as approved by the human, then rerun tox.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:BEGIN -->

Investigation confirmed both CLI branches only vary whether the helper's default HistorySettings argument is explicit. Focused and full tests, Ruff lint, and mypy pass. tox's coverage environment passes 131 tests at 100%; its format check also reports pre-existing formatting drift in tests/test_index.py.

Final focused verification: uv run pytest tests/test_pstq.py passed (30 tests). Full pytest passed 131 tests; Ruff lint and mypy passed. uv run tox confirmed the py313 coverage gate passes at 100%, but lint remains blocked because ruff format --check flags pre-existing formatting drift in tests/test_index.py and unrelated mixed line-ending edits in tests/test_pstq.py. No formatting changes were made outside TASK-009's assertions.

Human approved the formatter cleanup. Ran uv run ruff format tests/test_pstq.py tests/test_index.py; uv run tox now passes lint (Ruff check and format, mypy) and py313 (131 tests, 100% coverage).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Simplified search and attachment synchronization to always pass resolved HistorySettings, and hoisted zoneinfo imports to module scope. Updated CLI call assertions and applied approved Ruff formatting to tests/test_pstq.py and tests/test_index.py. Verified with uv run tox: Ruff lint/format, mypy, 131 tests, and 100% coverage all pass. No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @Josef
created: 2026-08-30 07:20
---
Human: Approved reformatting tests/test_pstq.py and tests/test_index.py to clear the formatter gate.
---

author: @Josef
created: 2026-08-30 07:20
---
Agent: Implementation and the approved formatting cleanup are ready for human review. uv run tox passes completely.
---
<!-- COMMENTS:END -->

<!-- SECTION:NOTES:END -->
