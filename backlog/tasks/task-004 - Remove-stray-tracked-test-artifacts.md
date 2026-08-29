---
id: TASK-004
title: Remove stray tracked test artifacts
status: To Do
assignee: []
created_date: '2026-08-29 15:25'
labels:
  - code-review
  - hygiene
dependencies: []
references: []
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
- [ ] #1 test.json and test_config.yaml are removed from version control
- [ ] #2 .gitignore prevents these local scratch files from being re-tracked
- [ ] #3 No documentation or test references the removed files, or references are updated to a sanitized example
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. `git rm --cached` the two files and delete them from the working tree if unused.
2. Add explicit ignore entries (or a broad pattern) so they cannot be re-added accidentally.
3. Grep the repo and docs for references to either file and clean them up.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:END -->
