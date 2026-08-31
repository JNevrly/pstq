---
id: TASK-012
title: Restore the release quality gate
status: Done
assignee: []
created_date: '2026-08-31 08:53'
updated_date: '2026-08-31 09:21'
labels: []
dependencies: []
modified_files:
  - pstq/pst.py
  - tests/test_index.py
  - tests/test_pst.py
priority: high
type: chore
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Restore a green quality baseline so the new CI and release workflows can gate releases. The project must satisfy its formatter, static type checker, and 100% coverage policy.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 uv run ruff format --check . passes
- [x] #2 uv run pytest --cov=pstq tests/ meets the configured 100% coverage threshold
- [x] #3 uv run tox passes
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Format the two reported files with Ruff.
2. Add focused adapter tests for attachment lookup errors, body property failures and invalid values, missing bodies, and invalid cached locators.
3. Add index tests for full-body requests with a foreign store ID or source mutation during synchronization.
4. Run the focused tests, then the complete tox quality gate and record verified results.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added focused tests for defensive pypff adapter failures and full-body synchronization guards. Formatting was applied to the previously failing source and test files. Verification passed: 141 tests at 100% coverage, Ruff check and format check, MyPy, and the complete tox suite.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Agent
created: 2026-08-31 09:18
---
Agent: Implementation and all acceptance criteria are verified. This project has no review status, so the task remains In Progress awaiting human acceptance.
---

author: Human
created: 2026-08-31 09:21
---
Human: Reviewed TASK-012 and approved closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Restored the release quality gate by formatting reported files and covering previously untested adapter and full-body synchronization error paths. Verified with the focused tests, the 141-test coverage run at 100%, and the complete tox suite.
<!-- SECTION:FINAL_SUMMARY:END -->
