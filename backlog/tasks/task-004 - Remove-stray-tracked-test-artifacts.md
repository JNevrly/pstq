---
id: TASK-004
title: Remove stray tracked test artifacts
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 15:25'
updated_date: '2026-08-29 17:33'
labels:
  - code-review
  - hygiene
dependencies: []
modified_files:
  - .gitignore
  - docs/code-review-2026-08-29.html
  - test.json
  - test_config.yaml
priority: medium
type: chore
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two local scratch files are checked into version control and are not build,
source, or documentation artifacts:

- `test.json` — an ~80 KB dump of a single retrieved message, including the raw
  HTML body of what appears to be a real message from a sample PST. Committing
  it risks leaking sample-archive content and bloats the repository.
- `test_config.yaml` — a personal config pointing at `temp/test.pst` and
  `temp/test.index.sqlite`, i.e. paths that only exist on one developer's
  machine.

`temp/` is already ignored, but these two files sit at the repository root and
are tracked. Remove them from version control and extend `.gitignore` so they
are not re-added. If a committed example config is genuinely wanted, replace it
with a sanitized template rather than a working developer config.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 test.json and test_config.yaml are removed from version control
- [x] #2 .gitignore prevents these local scratch files from being re-tracked
- [x] #3 No documentation or test references the removed files, or references are updated to a sanitized example
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Remove test.json from version control and the working tree.
2. Stop tracking test_config.yaml while preserving the user’s local file.
3. Add explicit ignore entries for both scratch files.
4. Update non-historical documentation references, then verify tracked files and repository references.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigation: both files are tracked. .gitignore already has an uncommitted test_config.yaml entry, and test_config.yaml itself has uncommitted local owner identity additions. docs/code-review-2026-08-29.html documents the review finding; historical Backlog task notes also reference the config. The working-tree config change conflicts with deleting the file, so confirmation is required before removal.

Requirement clarified: preserve the local config file while removing it from version control.

Implemented: removed test.json from the worktree and index; removed test_config.yaml from the index while retaining the local ignored copy; added explicit ignore entries; and generalized the code-review document to remove explicit scratch-file references. Verification: git diff --check and git diff --cached --check passed; git check-ignore confirms both names are ignored; docs/ and tests/ contain no references.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @human
created: 2026-08-29 17:32
---
Human: Preserve the uncommitted local test_config.yaml, but stop tracking it.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Removed both scratch artifacts from Git tracking. Deleted test.json from the worktree, retained the user-requested ignored local test_config.yaml, added explicit ignore rules, and removed filename references from the maintained code-review document.

Verified: no tracked artifact paths remain; test.json is absent while test_config.yaml remains local; Git recognizes both ignore rules; git diff --check and git diff --cached --check pass; and manual review plus repository scans found no references in docs/ or tests/. Historical Backlog records retain their prior references as task provenance.

No follow-up tasks or ADRs.
<!-- SECTION:FINAL_SUMMARY:END -->

Investigation: both files are tracked.  already has an uncommitted  entry, and  itself has uncommitted local owner identity additions.  documents the review finding; historical Backlog task notes also reference the config. The working-tree config change conflicts with deleting the file, so confirmation is required before removal.
<!-- SECTION:NOTES:END -->
