---
id: TASK-001.10
title: Document available PST query commands
status: Done
assignee:
  - '@root'
created_date: '2026-08-29 07:32'
updated_date: '2026-08-29 08:39'
labels: []
dependencies:
  - TASK-001.05
modified_files:
  - README.md
parent_task_id: TASK-001
priority: medium
type: docs
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Update the README for the implemented configured PST workflow without documenting commands that remain in later tasks.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 README explains read-only PST handling, SQLite cache behavior, and automatic search synchronization
- [x] #2 README documents Onacol archive configuration and the environment override names
- [x] #3 README provides accurate examples for status, folders, search, and show with their implemented filters
- [x] #4 README distinguishes currently available commands from planned thread and attachment features
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace the scaffold README with an operator-focused description of the read-only PST and disposable SQLite cache model.
2. Document YAML and environment configuration, including existing-path requirements.
3. Add verified command examples and describe stable JSON search/show IDs without promising unimplemented commands.
4. Check examples against CLI help and run the documentation-relevant project checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigation: the implemented interface consists of status, folders, search, and show. The bundled Onacol template exposes archive.pst_path and archive.index_path; environment names are PSTQ_ARCHIVE__PST_PATH and PSTQ_ARCHIVE__INDEX_PATH. Search supports the documented structured filters and limits results to 100; folders and show read the existing SQLite cache.

Implementation: replaced the README scaffold with an operator guide covering the read-only PST guarantee, disposable atomic SQLite cache, configured YAML/environment paths, synchronization behavior, stable IDs, JSON output, filters, bounded results, and SQLite-only show retrieval. It explicitly labels thread and attachment operations as unavailable.

Validation: regenerated the bundled config template, checked status/folders/search/show help against the examples, and ran `uv run tox` successfully (Ruff, formatting, mypy, 72 tests, 100% coverage).

Final validation remains valid after the UTF-8 regression fixes: uv run tox now passes 74 tests at 100% coverage.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @root
created: 2026-08-29 07:33
---
Agent: README documentation for the currently available commands is ready for human review. The configured Backlog states have no review state, so this task remains In Progress pending acceptance.
---

author: Human
created: 2026-08-29 08:39
---
Human: Accepted the README update and requested closure of TASK-001.10.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Documented the available PST query workflow in README.md: configuration, source/cache safety model, status, folders, search filters, stable result IDs, show, JSON output, and current limitations. Verified command help/template behavior and uv run tox (74 tests, 100% coverage). Final CLI-contract documentation remains in TASK-001.09 after its dependencies complete; no ADRs created.
<!-- SECTION:FINAL_SUMMARY:END -->
