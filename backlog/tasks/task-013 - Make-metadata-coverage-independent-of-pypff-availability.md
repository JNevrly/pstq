---
id: TASK-013
title: Make metadata coverage independent of pypff availability
status: Done
assignee: []
created_date: '2026-08-31 09:40'
updated_date: '2026-08-31 09:56'
labels: []
dependencies: []
references:
  - 'https://github.com/JNevrly/pstq/actions'
modified_files:
  - tests/test_metadata.py
  - tox.ini
priority: high
type: bug
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fix the CI-only coverage regression where metadata.py is 99% on GitHub runners without pypff, while local devcontainer runs reach 100% because pypff is installed. Tests must cover both callable and unavailable libpff version paths deterministically.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The metadata version helper is covered when pypff exposes a callable version API and when pypff is unavailable or has no callable version API
- [x] #2 The complete tox suite reaches the configured 100% coverage threshold in an environment without pypff
- [x] #3 The CI quality workflow passes on GitHub
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add explicit metadata tests for callable, non-callable, and unavailable pypff version APIs so coverage no longer depends on the host image.
2. Run the metadata tests and the standard quality suite.
3. Create an isolated temporary environment without system site packages, synchronize the locked project dependencies, and verify the coverage gate there.
4. Record results and leave the task ready for human acceptance after GitHub CI confirms the fix.

5. Make tox synchronize and run through its active environment so local checks cannot consume devcontainer-only system packages.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added deterministic tests for callable and non-callable pypff version APIs; the existing test covers import failure. Updated tox to synchronize locked dependencies and run tools in each active tox environment, avoiding devcontainer system site packages. Verified the py313 tox environment cannot import pypff and the complete tox suite passes with 142 tests and 100% coverage. GitHub CI confirmation remains pending.

Human confirmed that the GitHub CI quality workflow passes after the fix was pushed.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-31 09:56
---
Human: Confirmed GitHub CI passes and approved closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Made coverage deterministic across pypff availability by testing callable, non-callable, and unavailable version APIs, and by isolating tox environments from system site packages. Verified locally with 142 tests at 100% coverage and the complete tox suite; human confirmed GitHub CI passes.
<!-- SECTION:FINAL_SUMMARY:END -->
